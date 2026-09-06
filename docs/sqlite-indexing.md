# SQLite 索引与查询计划

> 本文所有 EXPLAIN 输出与耗时数据均来自本地实测:
> `experiments/sqlite-indexing/run_experiments.py`(SQLite 3.50,orders 表 100,000 行,
> 固定随机种子),完整日志见同目录 `report.txt` / `README.md`。
> 理论表述对照 sqlite.org 官方文档(queryplanner.html / optoverview.html / withoutrowid.html)。

## 1. 页、rowid 与两种 B-tree

SQLite 数据库文件就是一组固定大小的**页**(默认 page_size=4096,本实验库 2716 页 ≈ 10.6 MB)。
所有表和索引都是存在这些页上的 **B-tree**。SQLite 里有两种 B-tree:

- **table b-tree**:存表数据。每个叶子页放整行,键是 **rowid**。
- **index b-tree**:存索引。叶子页只放「索引列值 + rowid」,不放整行。

```
TABLE B-tree (orders, 100000 行)              INDEX B-tree (idx_orders_status)
                                              叶子: (status, rowid) 有序
page#1 (root)                                 page#1 (root)
  |                                             |
  +-- 内部页: 按 rowid 分隔                     +-- 内部页: 按 (status,rowid) 分隔
        |                                             |
        v                                             v
  [叶子页: rowid=1 -> 整行]                      [叶子页: ('cancelled', 67790) | ('cancelled', 48100)
  [叶子页: rowid=2 -> 整行]                              ('cancelled', 12904) | ...
  [叶子页: rowid=3 -> 整行]                              ('paid', 12) | ('paid', 37) | ...
  ... 整行含 note 等大字段                                ('refunded', 85) ...
```

关键差异:index b-tree 的叶子里只有「键 + rowid」,所以通常一个叶子页能放几百个条目,
索引远小于表(实验中 orders 表 10.3 MB,单列索引 1.4~2.8 MB)。

**rowid 与 INTEGER PRIMARY KEY**:声明 `id INTEGER PRIMARY KEY` 时,`id` 是 rowid 的别名,
按 id 查就是按 B-tree 键查,一步到位:

```
sqlite> EXPLAIN QUERY PLAN SELECT amount FROM orders WHERE id = 12345;
SEARCH orders USING INTEGER PRIMARY KEY (rowid=?)
实测 0.012 ms/次 —— 所有查询的基准下限。
```

没有声明 INTEGER PRIMARY KEY 的表也有隐藏 rowid;而 `WITHOUT ROWID` 表(见 §7)
没有 rowid,表本身按主键组织成 index b-tree。

## 2. 单列索引:从 SCAN 到 SEARCH

无索引时,`WHERE status = 'refunded'` 只能全表扫描:

```
-- 建 idx_orders_status 前
SEARCH? 不存在。计划:
SCAN orders
实测 9.79 ms/次 (命中 5099/100000 行)

-- 建索引后
CREATE INDEX idx_orders_status ON orders(status);
SEARCH orders USING INDEX idx_orders_status (status=?)
实测 6.72 ms/次
```

计划行怎么读:`SEARCH` = 在 B-tree 上做二分定位;`(status=?)` = 索引的哪一列被哪个
约束用上了;`SCAN` = 顺序扫描。§4 有完整对照表。

但要注意一个实测反例——**命中行多时索引反而更慢**:

```
WHERE status = 'paid'   (命中 54636 行, 54.6%)
计划仍是 SEARCH ... USING INDEX idx_orders_status (status=?)
实测 30.8 ms/次 —— 比无索引全扫(约 10ms)慢 3 倍!
```

原因:54636 次回表(见 §3)的随机页访问远贵于顺序扫一遍表。
而且 planner 看不出 paid 和 refunded 的区别——`sqlite_stat1` 只记录**平均值**
(见 §6),两个值都按「平均 20000 行」估计。教训:低选择性列单独建索引是负资产。

## 3. 复合索引、覆盖索引与回表

### 3.1 索引条目的物理排序

`CREATE INDEX idx_csd ON orders(customer_id, status, created_at)` 后,
索引 b-tree 的条目按**字典序**排列(等价于 SQL 的 ORDER BY customer_id, status, created_at),
并且**末尾隐式追加 rowid** 保证唯一性:

```
索引条目(逻辑顺序):                        排序规则演示:

(customer_id, status, created_at, rowid)     (123, 'cancelled', '2025-01-03', 450)
(1,    'paid',      '2025-01-01', 12)        (123, 'cancelled', '2025-02-11', 88)
(1,    'paid',      '2025-02-14', 57)        (123, 'paid',      '2025-01-09', 57)
(1,    'refunded',  '2025-01-09', 88)        (123, 'paid',      '2025-03-01', 512)
(1,    'shipped',   '2025-01-22', 450)       (123, 'refunded',  '2025-01-02', 88)   <- status 决定次序
(2,    'cancelled', '2025-01-05', 3)         (456, 'paid',      '2024-12-30', 2)    <- customer_id 优先
(2,    'paid',      '2025-01-17', 9)         (999, 'cancelled', '2025-06-01', 1000) <- 一切之前先比 customer_id
...                                          (同一 customer 内 status 有序, 同 status 内 date 有序)
```

两个直接推论,都被实验证实:

1. `ORDER BY customer_id, status` 可以直接按索引顺序读,**免排序**:
   ```
   SELECT customer_id, status FROM orders ORDER BY customer_id, status LIMIT 20;
   SCAN orders USING COVERING INDEX idx_csd          <- 无 TEMP B-TREE, 0.020 ms
   ```
   而 `ORDER BY status, customer_id`(顺序颠倒)索引帮不上:
   ```
   SCAN orders USING INDEX idx_orders_status
   USE TEMP B-TREE FOR LAST TERM OF ORDER BY         <- 9.49 ms
   ```

2. **最左前缀**(§5 详述):条目先按 customer_id 分段,所以只给 status 无法二分定位。

### 3.2 回表:USING INDEX vs USING COVERING INDEX

索引叶子里只有「索引列 + rowid」。如果查询还要别的列,就得拿 rowid 回 table b-tree
再取一次——**回表**,一行一跳:

```
-- idx_orders_status_amount(status, amount),查询只用到索引里的列:
SELECT amount FROM orders WHERE status = 'refunded';
SEARCH orders USING COVERING INDEX idx_orders_status_amount (status=?)
                                                            ^^^^^^^^ 关键字 COVERING
实测 1.44 ms/次

-- 换成要 note 列(不在任何索引里),每行回表一次:
SELECT id, note FROM orders WHERE status = 'refunded';
SEARCH orders USING INDEX idx_orders_status_amount (status=?)   <- 没有 COVERING
实测 14.58 ms/次 —— 同样 5099 行,慢 10 倍
```

`USING COVERING INDEX` 表示整条查询被索引自含,零回表。设计查询时尽量让它出现:
把 SELECT 里的小字段塞进索引尾部(`INDEX(status, amount)` → 查询只选这两列),
是最便宜的优化手段之一;`count(*)` 天然受益(0.134 ms)。

### 3.3 复合索引上的等值 + 范围

索引列的使用有「一刀切」性质:**第一个范围列之后的列不再参与定位**,只能当过滤器:

```
SELECT id FROM orders
WHERE customer_id = 123 AND status = 'paid' AND created_at >= '2025-06-01';

SEARCH orders USING COVERING INDEX idx_csd
  (customer_id=? AND status=? AND created_at>?)      -- 三列全部用上, 0.013 ms
```

把 `>=` 换成另一列的等值再想加第二个范围?范围列只能有一个,其余等值列必须排在它前面。
这也是复合索引列顺序设计的核心法则:**等值列在前,范围列收尾**。

## 4. EXPLAIN QUERY PLAN 输出对照表

实测出现的全部计划行(前缀 `QUERY PLAN`,缩进表示嵌套循环层级):

| 计划行 | 含义 | 实测备注 |
| --- | --- | --- |
| `SCAN orders` | 全表扫描(table b-tree 顺序读) | 无索引时, ~10 ms/10万行 |
| `SCAN orders USING INDEX x` | 全索引扫描(只扫索引,仍遍历全部条目) | 函数包裹列、`LIKE '%x'` 时出现 |
| `SCAN orders USING COVERING INDEX x` | 遍历覆盖索引的全部条目 | ORDER BY 走索引序时是**好事** |
| `SEARCH ... USING INDEX x (col=?)` | 经索引二分定位,之后回表 | |
| `SEARCH ... USING COVERING INDEX x (...)` | 经索引定位且零回表 | 最理想的读取方式 |
| `SEARCH ... USING INTEGER PRIMARY KEY (rowid=?)` | rowid 直接定位 | 0.012 ms 基准 |
| `SEARCH users_wr USING PRIMARY KEY (email=?)` | WITHOUT ROWID 表按主键定位 | 表即索引 |
| `USE TEMP B-TREE FOR ORDER BY` | 排序需临时 B-tree(内存/临时文件) | 换索引序可消除 |
| `USE TEMP B-TREE FOR LAST TERM OF ORDER BY` | 排序键前缀吻合,仅最后一项需排序 | `ORDER BY status, customer_id` |
| `USE TEMP B-TREE FOR (GROUP BY/DISTINCT)` | 分组/去重需临时结构 | 索引序吻合时可免 |
| `MULTI-INDEX OR` + `INDEX 1/INDEX 2` | OR 两分支各查一条索引后取并集去重 | `status=? OR customer_id=?` |
| `CO-ROUTINE (subquery-1)` | 子查询物化为协程逐行供给 | 常与 SCAN 叠加出现 |
| `SEARCH t ... (ANY(a) AND b=?)` | **skip-scan**:`ANY(a)` 表示跳过最左列 | 仅在 ANALYZE 之后出现(§6) |
| `LIST SUBQUERY`/`SCALAR SUBQUERY` | IN 子查询/标量子查询的执行方式 | |

判读口诀:**SEARCH 优于 SCAN;COVERING 优于非覆盖;看到 TEMP B-TREE 先想想能否换索引序;
SCAN USING INDEX 不一定比 SCAN 好**(条目数一样,只是行更窄)。

## 5. 最左前缀:列顺序决定可用性

对 `idx(customer_id, status, created_at)`,实测每种条件组合的计划:

| WHERE 条件 | 能用索引定位的列 | 计划 | 耗时 |
| --- | --- | --- | --- |
| customer=? AND status=? AND date>=? | 全部三列 | `(customer_id=? AND status=? AND created_at>?)` | 0.013 ms |
| customer=? AND status=? | 前两列 | `(customer_id=? AND status=?)` | 0.015 ms |
| 仅 customer=? | 最左一列 | `(customer_id=?)` | 0.021 ms |
| 仅 status=? | 0 列(跳过最左列) | 改走单列索引 `idx_orders_status` | 1.61 ms |
| customer=? AND date>=? | 仅第一列;date 不定位只过滤 | `(customer_id=?)` | 0.019 ms |

原理回到 §3.1 的排序示意:条目先按 customer_id 分段,不给最左列就不知道去哪个段里找;
中间列一旦缺失,它右侧的列虽然在段内大体有序,却失去了精确的分隔点。

两个例外,都实测过:

- **skip-scan**:最左列取值极少(如 2 种)时,planner 可以对每个取值各做一次定位,
  计划显示 `(ANY(a) AND b=?)`——但前提是先 ANALYZE(§6)。
- **IN 列表**:`customer_id IN (?,?)` 等价于对每个取值各定位一次,普通 SEARCH,0.044 ms。

设计法则:**把最常以等值出现、选择性最高的列放最左;等值列按 (a,b,c) 排,范围列最后;
能同时满足查询的 ORDER BY 更好**(免 TEMP B-TREE)。

## 6. 什么时候索引没用(以及 SQLite 的特别之处)

实测的失效与不失效清单(对照基准:走索引 0.072 ms):

**真失效(退化为 SCAN)**

| 写法 | 实测耗时 | 原因 |
| --- | --- | --- |
| `WHERE substr(created_at,1,7) = '2025-06'` | 6.48 ms | 索引按整列有序,函数结果无序 |
| `WHERE upper(status) = 'REFUNDED'` | 10.77 ms | 同上 |
| `WHERE customer_id + 0 = 123` | 6.40 ms | 表达式破坏了列→键的映射 |
| `WHERE email LIKE '%com'` | 23.86 ms | 前缀通配,无法转范围 |
| `WHERE email LIKE 'user1%'`(默认配置) | 19.49 ms | 见下方 LIKE 三条件 |

救援手段(实测有效):

- 表达式索引:`CREATE INDEX ... ON orders(lower(email))` →
  `SEARCH ... USING COVERING INDEX idx_email_lower (<expr>=?)`,0.038 ms。
  SQLite 3.9+ 支持表上的表达式索引,查询里写同样的表达式即可命中。
- 范围条件替代函数:`created_at >= '2025-06-01' AND created_at < '2025-07-01'`
  替代 `substr(...)=`,直接走索引。

**LIKE 前缀优化有三个前提**(官方 optoverview「The LIKE Optimization」,实验逐一验证):
默认 LIKE 大小写不敏感,而 BINARY 索引是大小写敏感的有序集合,两者对不上。只有两种组合能转范围:

1. 索引用默认 BINARY 排序 **且** `PRAGMA case_sensitive_like = ON`;
2. 索引声明为 `email COLLATE NOCASE` **且** 保持默认大小写不敏感 LIKE。

两种情况下计划都变成 `SEARCH ... (email>? AND email<?)`。

**OR 条件**:不同列的 OR 若各有索引,planner 用 `MULTI-INDEX OR`——两条索引各查一遍、
按 rowid 并集去重(实测 3.71 ms,优于单全扫)。经常写 OR 的场景可以考虑 UNION ALL 改写。
同列 OR(`a=? OR a=?`)会自动转 IN,普通 SEARCH。

**SQLite 与 MySQL 的一个重要差异**:语句里类型不匹配通常**不会**让索引失效。

```
SELECT id FROM orders WHERE customer_id = '123';   -- 列是 INTEGER, 值是字符串
SEARCH orders USING COVERING INDEX idx_csd (customer_id=?)    -- 仍然走索引, 0.017 ms
```

SQLite 按列亲和性(affinity)在比较前把 `'123'` 转成数字 123,索引键本来就是数字,照常二分。
真正会踩的坑是**无类型声明列的混合存储类**(SQLite 动态类型特有):

```
CREATE TABLE mixed(v);            -- 无类型 => 无 affinity
INSERT INTO mixed VALUES (123), ('123');
WHERE v = 123   -> 命中 rowid 1 (integer)   走索引
WHERE v = '123' -> 命中 rowid 2 (text)      走索引, 但彼此看不见对方的行!
```

两次查询都用了索引,却各自只命中一种存储类——这是**正确性**问题而非性能问题。
结论:列始终声明类型;字符串列永远用字符串比较、数字列永远用数字比较,别依赖隐式转换。

## 7. ANALYZE 与查询计划器

### 7.1 sqlite_stat1 记录了什么

`ANALYZE` 扫描索引采样,把统计写入 `sqlite_stat1`(tbl, idx, stat 三列,均带 `+` 的
`stat` 是「总行数 + 每列前缀平均重复数」):

```
tbl=orders  idx=idx_orders_created           stat=100000 274
tbl=orders  idx=idx_orders_cust_status_date  stat=100000 20 5 1
tbl=orders  idx=idx_orders_status            stat=100000 20000
tbl=users_wr idx=users_wr                    stat=5000 1
```

读法:`100000 20 5 1` = 表 10 万行;只按 customer_id 等值平均命中 20 行;
再叠加 status 等值平均 5 行;三列全用平均定位到 1 行。planner 的成本模型就是拿这些
数字做对数估计、在候选方案间算分。

### 7.2 ANALYZE 改变计划的实测案例

多数查询在 ANALYZE 前后计划不变(planner 的默认猜测已有 10 倍/对数规则兜底),
但有一类优化**没有统计就完全禁用**——index skip-scan。官方文档原话:
"a skip-scan is never used on a database that has not been analyzed"。
实测(20 万行表 t,索引 t_ab(a,b),a 只有 2 种取值,查询不带 a):

```
-- 删除 sqlite_stat1(未分析)
SELECT a FROM t WHERE b = 5;
SCAN t                                  实测 8.06 ms

-- ANALYZE 之后
SELECT a FROM t WHERE b = 5;
SEARCH t USING COVERING INDEX t_ab (ANY(a) AND b=?)     实测 0.002 ms
```

`ANY(a)` 的含义:planner 从 stat1 得知 a 平均 10 万行才一个不同值,于是对 a 的每个
可能取值各做一次 `(a,b)` 定位——两次二分 vs 20 万行扫描,快 4000 倍。
没有统计时 planner 只能假设「最左列平均重复 10 次」,不足 18 次跳扫不划算,直接禁用。

### 7.3 stat1 的盲区

`sqlite_stat1` 是**每个索引一个平均值**,没有按值的直方图(那在可选的 `sqlite_stat4` 里,
且默认 ANALYZE 只写 stat1)。后果在 §2 已经见过:`status='paid'`(54.6% 行)与
`status='refunded'`(5.1%)在 stat1 眼里都是「平均 20000 行」,planner 对两者都选了索引,
前者比全表扫描还慢 3 倍。所以:

- 低选择性列不要单独建索引——这不是 planner 调优能救的;
- 确实需要时,用 `sqlite_stat4`(`ANALYZE` 前设 `PRAGMA analysis_limit` 控制采样量;
  或 `PRAGMA optimize` 让 SQLite 自动在合适的时机 ANALYZE)。

## 8. WITHOUT ROWID 表

普通表 = table b-tree(按 rowid)+ 每个索引一棵 index b-tree。
`WITHOUT ROWID` 表**没有 rowid,整张表按主键组织成 index b-tree**,主键就是数据的物理顺序。
实测对照(5000 行,email 主键/唯一索引):

```
-- rowid 表 + UNIQUE INDEX(email)
SELECT name FROM users_rowid WHERE email = 'user123@example.com';
SEARCH users_rowid USING INDEX users_rowid_email (email=?)     -- 两跳: 索引 -> rowid -> 表

-- WITHOUT ROWID
SELECT name FROM users_wr WHERE email = 'user123@example.com';
SEARCH users_wr USING PRIMARY KEY (email=?)                    -- 一跳: 表即索引
```

dbstat 实测占用:

| 对象 | 占用 |
| --- | --- |
| users_rowid(表)+ users_rowid_email(唯一索引) | 184 KB + 156 KB = **340 KB** |
| users_wr(表即索引) | **192 KB(-44%)** |

5000 行小表上点查两者都在微秒级打平(0.002~0.005 ms),范围查询略快
(0.69 vs 0.74 ms);行越大、二级索引越多,rowid 方案要为每个二级索引多存一份主键,
差距会被放大。

**适用场景**:自然主键(email、code、URL 等)+ 行整体较小、以主键访问为主。
如配置表、映射表、`WITHOUT ROWID` 的多列复合主键关联表。
**不适用**:大行(BLOB/长文本,每页塞的条目少,主键 B-tree 变深)、必须依赖自增 rowid
写入局部性的高频插入表(INTEGER PRIMARY KEY 顺序追加最快)。

## 9. 索引设计检查清单

**建索引之前**

- [ ] 先 `EXPLAIN QUERY PLAN` 确认当前计划:找 `SCAN`、`TEMP B-TREE`、无 `COVERING` 的 `SEARCH`。
- [ ] 该查询的真实命中行数是多少?`SELECT count(*)` 验证——命中 >10% 行时索引常常是负优化(§2)。

**列选择与顺序**

- [ ] 等值条件列在前(选择性高的更前),范围条件列收尾,一个索引只放一个范围列(§3.3、§5)。
- [ ] 复合索引最左列必须出现在绝大多数目标查询里(§5)。
- [ ] 低选择性列(status 5 种值)不单独建索引;要建也作为复合索引的中前列(§2、§7.3)。
- [ ] ORDER BY / GROUP BY 的列序若能匹配索引序,可免 TEMP B-TREE(§3.1)。

**覆盖与回表**

- [ ] 高频查询尽量做到 `USING COVERING INDEX`:把 SELECT 的小字段追加到索引尾部(§3.2)。
- [ ] 出现非覆盖 `SEARCH USING INDEX` + 大命中行数 = 回表风暴,优先加列或改写查询。

**写法避坑**

- [ ] 不对列做函数/算术:`substr(col,..)`、`upper(col)`、`col+0`;改范围条件或建表达式索引(§6)。
- [ ] LIKE 前缀搜索:确认 `case_sensitive_like` 与索引排序规则(NOCASE/BINARY)匹配(§6)。
- [ ] 不依赖隐式类型转换:数字列用数字比、文本列用文本比;列必须声明类型(§6)。
- [ ] 不同列的大 OR 考虑 UNION ALL 或 `MULTI-INDEX OR` 是否已生效(§6)。

**维护**

- [ ] 数据量或分布显著变化后跑 `ANALYZE`(或依赖 `PRAGMA optimize`);skip-scan 等优化没有统计不启用(§7.2)。
- [ ] 索引不是免费的:每个索引都是一棵要随写维护的 B-tree;定期删除从未被 SEARCH 计划用到的索引。
- [ ] 部署前用真实数据量验证计划——100 行上正确的计划在 100 万行上可能完全不同。

**表设计**

- [ ] 主键访问为主的自然键小表考虑 `WITHOUT ROWID`;大行/高频自增插入用普通 rowid 表(§8)。
- [ ] 永远声明 `INTEGER PRIMARY KEY` 或明确主键,别让 rowid 不可控。

## 10. 参考

- 官方文档:Query Planning (queryplanner.html)、The Query Planner (optoverview.html)、
  Indexes (lang_creatindex.html)、WITHOUT ROWID (withoutrowid.html)、ANALYZE (lang_analyze.html)
- 本地实验:`experiments/sqlite-indexing/run_experiments.py`(可复跑,数据库已保留)
