# SQLite 索引与查询计划 —— 实验记录

配套主文档:[`../../docs/sqlite-indexing.md`](../../docs/sqlite-indexing.md)(结论的完整叙述版)。
本目录是全部结论的实验证据:可复跑脚本 + 生成的数据库 + 完整运行日志。

## 目录内容

| 文件 | 说明 |
| --- | --- |
| `run_experiments.py` | 实验脚本:建库 → 造 10 万行数据 → 逐实验打印 EXPLAIN QUERY PLAN + 耗时 |
| `sqlite-indexing.db` | 脚本实际运行后保留的数据库(~32 MB,含实验辅助表 `t`/`mixed`) |
| `report.txt` | 最近一次运行写入的完整输出 |
| `run_log.txt` | 同上(运行时控制台重定向的副本) |

## 复跑方式

```bash
cd experiments/sqlite-indexing
python run_experiments.py        # 全程约 7 秒;每次运行先删除并重建 .db
```

环境:Windows 10 / Python 3.14(sqlite3 引擎 3.50.4,纯标准库,无第三方依赖);
另用系统 `sqlite3` CLI(3.50.6)读取 `dbstat` 统计各对象占页(Python 侧模块未编入 dbstat,脚本内自动回退到 CLI)。

## 数据集

`orders` 表 100,000 行:

```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,      -- rowid 别名
    customer_id INTEGER,         -- 5000 种取值(平均每种 20 行)
    product_id  INTEGER,         -- 500 种取值
    status TEXT,                 -- 5 种取值:paid 54.6% / shipped 20% / cancelled 10.1% / pending 10.1% / refunded 5.1%
    amount REAL, created_at TEXT, email TEXT, note TEXT
);
```

对照表:`users_rowid`(rowid 表 + email 唯一索引,5000 行)vs `users_wr`(WITHOUT ROWID,email 主键)。
随机种子固定(42),数据完全可复现。

## 实验结果速览

数字均为缓存预热后单次平均耗时(SQLite 3.50.4,page_size=4096)。EXPLAIN 输出见 `report.txt`。

### 实验 1:全表扫描 vs 单列索引 vs rowid 点查

| 查询 | 计划 | 耗时 |
| --- | --- | --- |
| `WHERE status='refunded'`(5.1% 行)无索引 | `SCAN orders` | 9.79 ms |
| 同查询,建 `idx_orders_status` 后 | `SEARCH ... USING INDEX (status=?)` | 6.72 ms |
| 同查询但 `status='paid'`(54.6% 行) | 仍 `SEARCH USING INDEX` | **30.8 ms(比全扫还慢 3 倍)** |
| `WHERE id=?` rowid 点查(基准) | `SEARCH ... USING INTEGER PRIMARY KEY (rowid=?)` | 0.012 ms |

要点:命中行多是"回表风暴";stat1 只存平均值,planner 看不出 `paid` 和 `refunded` 的差别。

### 实验 2:复合索引最左前缀 `idx(customer_id, status, created_at)`

| 查询条件 | 计划关键行 | 耗时 |
| --- | --- | --- |
| customer+status+date>= | `SEARCH ... COVERING INDEX (customer_id=? AND status=? AND created_at>?)` | 0.013 ms |
| 只有 customer(最左列) | `(customer_id=?)` | 0.021 ms |
| 只有 status(跳过最左列) | 改用另一条单列索引 | 1.61 ms |
| customer+date>=(跳过中间列) | `(customer_id=?)`,date 列只能过滤不能定位 | 0.019 ms |
| ORDER BY customer_id,status | `SCAN ... USING COVERING INDEX`(免排序) | 0.020 ms |
| ORDER BY status,customer_id | `USE TEMP B-TREE FOR LAST TERM OF ORDER BY` | 9.49 ms |

### 实验 3:覆盖索引 `idx(status, amount)`

| 查询 | 计划 | 耗时 |
| --- | --- | --- |
| `SELECT amount WHERE status=?` | `USING COVERING INDEX` | 1.44 ms |
| `SELECT id, note WHERE status=?`(回表) | `USING INDEX`(无 COVERING) | 14.58 ms(10 倍差距) |
| `SELECT count(*) WHERE status=?` | `USING COVERING INDEX` | 0.134 ms |

### 实验 4:索引"失效"写法

| 写法 | 计划 | 耗时(对照基准 0.072 ms) |
| --- | --- | --- |
| `substr(created_at,1,7)=?` | `SCAN`(全索引扫) | 6.48 ms |
| `upper(status)=?` | `SCAN` | 10.77 ms |
| `customer_id+0=?` | `SCAN` | 6.40 ms |
| `customer_id = '123'`(字符串字面量) | **仍 `SEARCH`** | 0.017 ms |
| `email LIKE '%com'` | `SCAN` | 23.86 ms |
| `email LIKE 'user1%'`(默认 LIKE + BINARY 索引) | `SCAN`(未用前缀优化) | 19.49 ms |
| 同上 + `PRAGMA case_sensitive_like=ON` | `SEARCH (email>? AND email<?)` | 转为范围扫 |
| 同上 + `COLLATE NOCASE` 索引 | `SEARCH (email>? AND email<?)` | 同上 |
| `status=? OR customer_id=?` | `MULTI-INDEX OR`(两条索引各查一遍取并集) | 3.71 ms |
| `customer_id IN (?,?)` | 普通 `SEARCH`(IN 列表) | 0.044 ms |
| 救援:`lower(email)=?` + 表达式索引 | `SEARCH ... (<expr>=?)` | 0.038 ms |

**重要发现(SQLite 与 MySQL 不同)**:`customer_id = '123'` 并不会让索引失效——SQLite 按列亲和性把 `'123'` 转成数字后再查,索引照用。真正会踩的是**无类型声明列的混合存储类**:`CREATE TABLE mixed(v)` 插入 `123` 和 `'123'` 后,两个查询各自走索引却各自只命中一种存储类的行(正确性陷阱)。见 `report.txt` 实验 4 末尾。

### 实验 5:ORDER BY / GROUP BY 与 TEMP B-TREE

- `ORDER BY created_at LIMIT 5`(索引列):`SCAN ... USING COVERING INDEX`,0.030 ms——直接从索引最小端读 5 行,DESC 同理(索引可反向扫描)。
- `ORDER BY note LIMIT 5`(非索引列):`SCAN orders` + `USE TEMP B-TREE FOR ORDER BY`,19.81 ms。
- `GROUP BY status`(有 status 索引):索引本身有序,免 TEMP B-TREE,3.45 ms。

### 实验 6:ANALYZE 与 sqlite_stat1

ANALYZE 产出的 `sqlite_stat1`(tbl / idx / stat 三列):

```
tbl=orders  idx=idx_orders_created           stat=100000 274
tbl=orders  idx=idx_orders_cust_status_date  stat=100000 20 5 1
tbl=orders  idx=idx_orders_status            stat=100000 20000
```

解读:`100000 274` = 表 10 万行;该索引平均每个不同 created_at 值对应 274 行;
复合索引 `100000 20 5 1` = customer 20 行 → (customer,status) 5 行 → 三列定位 1 行。

**skip-scan 硬性开关实验**(官方文档:"a skip-scan is never used on a database that has not been analyzed"):

| 条件 | 计划 | 耗时 |
| --- | --- | --- |
| 20 万行表 `t(a,b)`,a 仅 2 种值,查询 `WHERE b=?`,删除 sqlite_stat1 | `SCAN t` | 8.06 ms |
| 同查询,`ANALYZE` 后 | `SEARCH t USING COVERING INDEX t_ab (ANY(a) AND b=?)` | 0.002 ms(4000 倍) |

其中 `ANY(a)` 即跳过最左列、按 a 的每个取值"跳跃"定位的 skip-scan。

### 实验 7:WITHOUT ROWID vs rowid 表 + 唯一索引(dbstat 实测占页)

| 对象 | 占用 |
| --- | --- |
| `users_rowid`(表,184KB)+ `users_rowid_email`(唯一索引,156KB) | 合计 340 KB |
| `users_wr`(WITHOUT ROWID,主键即表) | **192 KB(省 44%)** |

计划上,rowid 表经索引查 `name` 是 `USING INDEX (email=?)`(索引→rowid→回表两跳);
WITHOUT ROWID 是 `USING PRIMARY KEY (email=?)`(一跳)。5000 行小表上点查耗时几乎相同(均 <0.005 ms),
范围查询略快(0.69 vs 0.74 ms);存储优势是确定的,行越大、二级索引越多,差距越大。

## 官方文档交叉验证

- skip-scan 必须先 ANALYZE:sqlite.org `optoverview.html` "The Skip-Scan Optimization" —— 实验复现一致。
- LIKE 优化仅两种组合:BINARY 排序 + `case_sensitive_like=ON`,或 NOCASE 排序 + 默认(大小写不敏感)LIKE —— 实验 4 两个 SEARCH 计划复现一致。

---

## 交付说明(主 agent 注)

`sqlite-indexing.db`(约 34 MB)不入公开仓库,由 `python run_experiments.py` 一键重建(固定随机种子,结果可复现);完整真实输出见 `report.txt` / `run_log.txt`。
