#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite 索引与查询计划实验脚本
================================
自动完成:建库 -> 造 10 万行测试数据 -> 逐个实验(EXPLAIN QUERY PLAN + 实际耗时)
-> 生成 sqlite-indexing.db 与 report.txt

运行: python run_experiments.py
依赖: 仅 Python 标准库 sqlite3(等价于 sqlite3 命令行工具的引擎)

每个实验都会打印:
  - 使用的 SQL
  - EXPLAIN QUERY PLAN 的真实输出
  - 实际耗时(重复多次取平均)
"""

import os
import random
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "sqlite-indexing.db")
REPORT_PATH = os.path.join(BASE_DIR, "report.txt")

N_ROWS = 100_000          # orders 表行数
N_CUSTOMERS = 5_000
N_PRODUCTS = 500
STATUSES = ["paid", "shipped", "pending", "cancelled", "refunded"]
STATUS_WEIGHTS = [0.55, 0.20, 0.10, 0.10, 0.05]  # refunded 很少见

random.seed(42)

_out = []


def out(line: str = "") -> None:
    print(line)
    _out.append(line)


def section(title: str) -> None:
    bar = "=" * 78
    out()
    out(bar)
    out(title)
    out(bar)


def explain(conn: sqlite3.Connection, sql: str, params=()) -> list[tuple]:
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return [(r[3]) for r in rows]  # 第 4 列是 detail


def show_plan(conn: sqlite3.Connection, label: str, sql: str, params=()) -> None:
    out(f"\n--- PLAN [{label}] ---")
    out(f"SQL: {sql}")
    if params:
        out(f"params: {params!r}")
    for d in explain(conn, sql, params):
        out(f"  {d}")


def timed(conn: sqlite3.Connection, sql: str, params=(), repeat: int = 20,
          fetch: bool = True) -> float:
    """执行 SQL 若干次,返回单次平均耗时(毫秒)。"""
    # 预热一次
    cur = conn.execute(sql, params)
    cur.fetchall() if fetch else cur.fetchone()
    t0 = time.perf_counter()
    for _ in range(repeat):
        cur = conn.execute(sql, params)
        cur.fetchall() if fetch else cur.fetchone()
    return (time.perf_counter() - t0) * 1000.0 / repeat


def compare(conn: sqlite3.Connection, label: str, sql: str, params=(),
            repeat: int = 20) -> None:
    ms = timed(conn, sql, params, repeat)
    n = conn.execute("SELECT count(*) FROM (" + sql + ")", params).fetchone()[0]
    out(f"TIME [{label}]: {ms:9.3f} ms/次  (rows={n}, repeat={repeat})")


# --------------------------------------------------------------------------
# 1. 建库 + 造数据
# --------------------------------------------------------------------------

def build_db() -> sqlite3.Connection:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA page_size   = 4096;

        CREATE TABLE orders (
            id          INTEGER PRIMARY KEY,   -- rowid 别名
            customer_id INTEGER NOT NULL,
            product_id  INTEGER NOT NULL,
            status      TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            created_at  TEXT    NOT NULL,      -- 'YYYY-MM-DD'
            email       TEXT,
            note        TEXT
        );
    """)

    day0 = time.mktime(time.strptime("2025-01-01", "%Y-%m-%d"))
    domains = ["example.com", "mail.com", "test.org"]
    rows = []
    for i in range(1, N_ROWS + 1):
        cust = random.randint(1, N_CUSTOMERS)
        prod = random.randint(1, N_PRODUCTS)
        status = random.choices(STATUSES, STATUS_WEIGHTS)[0]
        amount = round(random.uniform(5, 2000), 2)
        ts = day0 + random.randint(0, 364) * 86400
        created = time.strftime("%Y-%m-%d", time.localtime(ts))
        email = f"user{cust}@{random.choice(domains)}"
        note = f"order note number {i} " + "x" * random.randint(0, 40)
        rows.append((i, cust, prod, status, amount, created, email, note))

    conn.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()

    # WITHOUT ROWID 对照表(实验 7 用),先不带额外索引
    conn.executescript("""
        CREATE TABLE users_rowid (
            email TEXT NOT NULL,
            name  TEXT NOT NULL
        );
        CREATE UNIQUE INDEX users_rowid_email ON users_rowid(email);

        CREATE TABLE users_wr (
            email TEXT NOT NULL PRIMARY KEY,
            name  TEXT NOT NULL
        ) WITHOUT ROWID;
    """)
    urows = [(f"user{c}@example.com", f"cust-{c}") for c in range(1, N_CUSTOMERS + 1)]
    conn.executemany("INSERT INTO users_rowid VALUES (?,?)", urows)
    conn.executemany("INSERT INTO users_wr VALUES (?,?)", urows)
    conn.commit()
    return conn


# --------------------------------------------------------------------------
# 2. 实验
# --------------------------------------------------------------------------

def exp0_schema(conn):
    section("实验 0:表结构与基础统计")
    for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"):
        out(f"{r[0]}\n    {r[1]}")
    out(f"\norders 行数 = {conn.execute('SELECT count(*) FROM orders').fetchone()[0]}")
    out(f"page_size  = {conn.execute('PRAGMA page_size').fetchone()[0]}")
    out(f"page_count = {conn.execute('PRAGMA page_count').fetchone()[0]}")
    out(f"db 总大小约 = {conn.execute('PRAGMA page_count').fetchone()[0] * 4 / 1024:.1f} MB")
    out("\nrowid 范围(id 列即 rowid 别名):")
    out(f"  min={conn.execute('SELECT min(id) FROM orders').fetchone()[0]}, "
        f"max={conn.execute('SELECT max(id) FROM orders').fetchone()[0]}")
    out("\nstatus 分布:")
    for s, c in conn.execute("SELECT status, count(*) FROM orders GROUP BY status ORDER BY 2 DESC"):
        out(f"  {s:10s} {c:6d}  ({c / N_ROWS:.1%})")


def exp1_fullscan_vs_index(conn):
    section("实验 1:无索引全表扫描 vs 单列索引点查")
    sql = "SELECT id, amount FROM orders WHERE status = ?"
    show_plan(conn, "无索引", sql, ("refunded",))
    compare(conn, "无索引 全表扫描", sql, ("refunded",), repeat=5)

    conn.execute("CREATE INDEX idx_orders_status ON orders(status)")
    show_plan(conn, "有 idx_orders_status", sql, ("refunded",))
    compare(conn, "有索引 SEARCH", sql, ("refunded",), repeat=50)

    out("\n对照:命中行数极多的条件(planner 仍可能选索引,也可能改回扫描,看统计)")
    show_plan(conn, "status=paid(约55%行)", sql, ("paid",))
    compare(conn, "有索引 but 命中55%", sql, ("paid",), repeat=5)

    out("\nrowid 点查(基准):")
    sql2 = "SELECT amount FROM orders WHERE id = ?"
    show_plan(conn, "rowid 点查", sql2, (12345,))
    compare(conn, "rowid 点查", sql2, (12345,), repeat=200)


def exp2_composite_leftmost(conn):
    section("实验 2:复合索引与最左前缀")
    conn.execute("DROP INDEX IF EXISTS idx_orders_cust_status_date")
    conn.execute("""CREATE INDEX idx_orders_cust_status_date
                    ON orders(customer_id, status, created_at)""")

    cases = [
        ("等值 customer+status+范围 date",
         "SELECT id FROM orders WHERE customer_id=? AND status=? AND created_at>=?",
         (123, "paid", "2025-06-01")),
        ("等值 customer+status",
         "SELECT id FROM orders WHERE customer_id=? AND status=?",
         (123, "paid")),
        ("只有最左列 customer",
         "SELECT id FROM orders WHERE customer_id=?",
         (123,)),
        ("跳过最左列:只给 status",
         "SELECT id FROM orders WHERE status=?",
         ("refunded",)),
        ("跳过中间列:customer+date",
         "SELECT id FROM orders WHERE customer_id=? AND created_at>=?",
         (123, "2025-06-01")),
        ("全表 ORDER BY 复合索引列(免排序)",
         "SELECT customer_id, status FROM orders ORDER BY customer_id, status LIMIT 20",
         ()),
        ("ORDER BY 顺序与索引不符(需 TEMP B-TREE)",
         "SELECT customer_id, status FROM orders ORDER BY status, customer_id LIMIT 20",
         ()),
        ("GROUP BY 非索引序(TEMP B-TREE)",
         "SELECT status, count(*) FROM orders GROUP BY status",
         ()),
    ]
    for label, sql, params in cases:
        show_plan(conn, label, sql, params)
        reps = 5 if not params else 100
        compare(conn, label, sql, params, repeat=reps)


def exp3_covering_index(conn):
    section("实验 3:覆盖索引(USING COVERING INDEX)")
    conn.execute("""CREATE INDEX idx_orders_status_amount
                    ON orders(status, amount)""")

    sql_cov = "SELECT amount FROM orders WHERE status = ?"
    show_plan(conn, "覆盖索引:只取 status/amount", sql_cov, ("refunded",))
    compare(conn, "COVERING INDEX", sql_cov, ("refunded",), repeat=50)

    sql_ncov = "SELECT id, note FROM orders WHERE status = ?"
    show_plan(conn, "非覆盖:要回表取 note", sql_ncov, ("refunded",))
    compare(conn, "INDEX + 回表", sql_ncov, ("refunded",), repeat=50)

    sql_cov2 = "SELECT count(*) FROM orders WHERE status = ?"
    show_plan(conn, "count(*) 走覆盖索引", sql_cov2, ("refunded",))
    compare(conn, "COVERING count(*)", sql_cov2, ("refunded",), repeat=50)

    out("\n索引内部结构 peek(复合索引键值示例,来自子查询模拟):")
    for r in conn.execute(
        """SELECT status, amount, id FROM (
               SELECT status, amount, id, rowid AS rn FROM orders LIMIT 5)"""):
        out(f"  key=({r[0]}, {r[1]}) -> rowid={r[2]}")


def exp4_broken_indexes(conn):
    section("实验 4:索引失效的常见写法")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_orders_email
                    ON orders(email)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_orders_created
                    ON orders(created_at)""")

    cases = [
        ("基准:created_at 直接等值",
         "SELECT id FROM orders WHERE created_at = ?", ("2025-06-15",)),
        ("函数包裹列:substr(created_at,1,7)=?",
         "SELECT id FROM orders WHERE substr(created_at,1,7) = ?", ("2025-06",)),
        ("函数包裹列:upper(status)=?",
         "SELECT id FROM orders WHERE upper(status) = ?", ("REFUNDED",)),
        ("隐式类型转换:customer_id 与字符串比较",
         "SELECT id FROM orders WHERE customer_id = ?", ("123",)),
        ("LIKE 后缀通配 '%com'",
         "SELECT id FROM orders WHERE email LIKE ?", ("%com",)),
        ("LIKE 前缀通配 'user1%'(可用索引)",
         "SELECT id FROM orders WHERE email LIKE ?", ("user1%",)),
        ("OR 连接两个不同列(各走各索引 or 全扫)",
         "SELECT id FROM orders WHERE status=? OR customer_id=?",
         ("refunded", 123)),
        ("同列 OR 可走 IN 优化",
         "SELECT id FROM orders WHERE customer_id IN (?,?)", (123, 456)),
        ("对索引列做算术:customer_id+0=?",
         "SELECT id FROM orders WHERE customer_id+0 = ?", (123,)),
    ]
    for label, sql, params in cases:
        show_plan(conn, label, sql, params)
        reps = 5 if label.startswith(("OR 连接",)) else 50
        compare(conn, label, sql, params, repeat=reps)

    out("\n补充:表达式索引可以把'函数包裹列'救回来")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_orders_email_lower
                    ON orders(lower(email))""")
    sql = "SELECT id FROM orders WHERE lower(email) = ?"
    show_plan(conn, "表达式索引", sql, ("user123@example.com",))
    compare(conn, "表达式索引", sql, ("user123@example.com",), repeat=50)

    out("\n补充:LIKE 前缀优化的前提(case_sensitive_like / NOCASE 索引)")
    sql = "SELECT id FROM orders WHERE email LIKE ?"
    out("默认 LIKE 大小写不敏感 + BINARY 索引 => 不能转 range:")
    show_plan(conn, "LIKE 默认", sql, ("user1%",))
    conn.execute("PRAGMA case_sensitive_like = ON")
    out("PRAGMA case_sensitive_like=ON 后 => 可转 range:")
    show_plan(conn, "LIKE csl=ON", sql, ("user1%",))
    conn.execute("PRAGMA case_sensitive_like = OFF")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_orders_email_nocase
                    ON orders(email COLLATE NOCASE)""")
    out("默认 LIKE + COLLATE NOCASE 索引 => 也可转 range:")
    show_plan(conn, "LIKE + NOCASE 索引", sql, ("user1%",))

    out("\n补充:无类型声明列的混合存储类(正确性陷阱,不是性能问题)")
    conn.executescript("""
        DROP TABLE IF EXISTS mixed;
        CREATE TABLE mixed(v);            -- 无类型 => 无 affinity
        CREATE INDEX idx_mixed ON mixed(v);
        INSERT INTO mixed VALUES (123), ('123'), (456);
    """)
    out(f"  WHERE v = 123   -> {conn.execute('SELECT rowid, typeof(v) FROM mixed WHERE v=123').fetchall()}")
    q123 = "SELECT rowid, typeof(v) FROM mixed WHERE v='123'"
    out(f"  WHERE v = '123' -> {conn.execute(q123).fetchall()}")
    show_plan(conn, "mixed v='123'", "SELECT rowid FROM mixed WHERE v = ?", ("123",))
    out("  两次查询都走索引,但各自只能命中同存储类的行。")


def exp5_orderby_groupby(conn):
    section("实验 5:ORDER BY / GROUP BY 与索引序、TEMP B-TREE")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_orders_created
                    ON orders(created_at)""")
    # 单列索引也可用于 ORDER BY ... LIMIT(经典 top-1 优化)
    cases = [
        ("ORDER BY 索引列 LIMIT 5(免全排序)",
         "SELECT id, created_at FROM orders ORDER BY created_at LIMIT 5", ()),
        ("ORDER BY 索引列(无 LIMIT,顺序扫描全表)",
         "SELECT count(*) FROM (SELECT id, created_at FROM orders ORDER BY created_at)", ()),
        ("ORDER BY 非索引列 note",
         "SELECT id FROM orders ORDER BY note LIMIT 5", ()),
        ("ORDER BY 索引列但反向 DESC",
         "SELECT id, created_at FROM orders ORDER BY created_at DESC LIMIT 5", ()),
        ("GROUP BY status(有 idx_orders_status 单列索引)",
         "SELECT status, count(*) FROM orders GROUP BY status", ()),
        ("DISTINCT email",
         "SELECT DISTINCT email FROM orders LIMIT 10", ()),
    ]
    for label, sql, params in cases:
        show_plan(conn, label, sql, params)
        compare(conn, label, sql, params, repeat=5)


def exp6_analyze(conn):
    section("实验 6:ANALYZE 与 sqlite_stat1 对 planner 的影响")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_orders_status
                    ON orders(status)""")
    out("当前已有索引:")
    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name"):
        out(f"  {r[0]}")

    out("\n--- ANALYZE 前:两条候选索引,planner 没有统计信息 ---")
    sql = "SELECT id FROM orders WHERE customer_id = ? AND status = ?"
    show_plan(conn, "ANALYZE 前", sql, (123, "paid"))
    compare(conn, "ANALYZE 前", sql, (123, "paid"), repeat=50)

    out("\n--- ANALYZE 后 ---")
    t0 = time.perf_counter()
    conn.execute("ANALYZE")
    out(f"ANALYZE 耗时 {(time.perf_counter()-t0)*1000:.1f} ms")
    out("sqlite_stat1 内容:")
    for r in conn.execute("SELECT tbl, idx, stat FROM sqlite_stat1 ORDER BY tbl, idx"):
        out(f"  tbl={r[0]:14s} idx={str(r[1]):30s} stat={r[2]}")

    show_plan(conn, "ANALYZE 后", sql, (123, "paid"))
    compare(conn, "ANALYZE 后", sql, (123, "paid"), repeat=50)

    out("\n--- ANALYZE 后 range 条件:created_at 范围查询 ---")
    sql2 = "SELECT id FROM orders WHERE created_at >= ? AND created_at < ?"
    show_plan(conn, "range", sql2, ("2025-06-01", "2025-06-02"))
    compare(conn, "range 1天", sql2, ("2025-06-01", "2025-06-02"), repeat=50)

    out("\n提示:查询级的替代方案 —— PRAGMA optimize / 'ANALYZE sqlite_schema'")

    out("\n--- ANALYZE 的硬性开关效应:index skip-scan 依赖 sqlite_stat1 ---")
    conn.executescript("""
        DROP TABLE IF EXISTS t;
        CREATE TABLE t(a INT, b INT);
    """)
    rng = random.Random(7)
    conn.executemany("INSERT INTO t VALUES(?,?)",
                     [(rng.choice([1, 2]), rng.randint(0, 99999))
                      for _ in range(200000)])
    conn.execute("CREATE INDEX t_ab ON t(a, b)")  # a 只有 2 种取值
    sql3 = "SELECT a FROM t WHERE b = ?"          # 没给最左列 a
    conn.execute("DELETE FROM sqlite_stat1")      # 抹掉统计 => 关闭 skip-scan
    show_plan(conn, "无 stat1", sql3, (5,))
    compare(conn, "无 stat1 全表扫描", sql3, (5,), repeat=20)
    conn.execute("ANALYZE")
    for r in conn.execute("SELECT idx, stat FROM sqlite_stat1 WHERE tbl='t'"):
        out(f"  sqlite_stat1: idx={r[0]} stat={r[1]}")
    show_plan(conn, "ANALYZE 后 skip-scan", sql3, (5,))
    compare(conn, "ANALYZE 后 skip-scan", sql3, (5,), repeat=20)


def exp7_without_rowid(conn):
    conn.commit()  # 释放前面实验可能残留的隐式写事务(dbstat/CLI 才能读到库)
    section("实验 7:WITHOUT ROWID vs rowid 表 + 唯一索引")
    out("users_rowid:普通 rowid 表 + UNIQUE INDEX(email)")
    out("users_wr   :WITHOUT ROWID,email 即主键(表本身就是一棵索引 B-tree)")

    # 各对象占用页数:优先用 dbstat 虚表,不可用时退化到 sqlite3 CLI
    def page_stats():
        try:
            return conn.execute(
                "SELECT name, sum(pgsize) FROM dbstat "
                "GROUP BY name ORDER BY 2 DESC").fetchall()
        except sqlite3.OperationalError:
            import subprocess
            q = ("SELECT name, sum(pgsize) FROM dbstat "
                 "GROUP BY name ORDER BY 2 DESC;")
            r = subprocess.run(["sqlite3", DB_PATH, q], capture_output=True,
                               text=True)
            return [(p.split("|")[0], int(p.split("|")[1]))
                    for p in r.stdout.strip().splitlines() if "|" in p]

    out("各对象占用存储(dbstat, 单位 KB):")
    for name, size in page_stats():
        out(f"  {name:24s} {size / 1024:8.1f} KB")
    out("  => users_wr(表即索引) vs users_rowid(表)+users_rowid_email(索引)")

    sql_r = "SELECT name FROM users_rowid WHERE email = ?"
    sql_w = "SELECT name FROM users_wr   WHERE email = ?"
    show_plan(conn, "rowid 表 UNIQUE 索引", sql_r, ("user123@example.com",))
    show_plan(conn, "WITHOUT ROWID 主键", sql_w, ("user123@example.com",))
    for _ in range(3):
        tr = timed(conn, sql_r, ("user123@example.com",), repeat=500)
        tw = timed(conn, sql_w, ("user123@example.com",), repeat=500)
        out(f"  点查: rowid表+索引 {tr:.4f} ms | WITHOUT ROWID {tw:.4f} ms")

    sql_rr = "SELECT email, name FROM users_rowid WHERE email BETWEEN ? AND ?"
    sql_wr = "SELECT email, name FROM users_wr   WHERE email BETWEEN ? AND ?"
    show_plan(conn, "rowid表 range(经唯一索引)", sql_rr, ("user100@", "user200@"))
    show_plan(conn, "WITHOUT ROWID range(直接扫表)", sql_wr, ("user100@", "user200@"))
    tr = timed(conn, sql_rr, ("user100@", "user200@"), repeat=100)
    tw = timed(conn, sql_wr, ("user100@", "user200@"), repeat=100)
    out(f"  range 查: rowid表+索引 {tr:.3f} ms | WITHOUT ROWID {tw:.3f} ms")

    out("\n结论方向:WITHOUT ROWID 主键表少一次'索引->rowid->表'的跳转,")
    out("且省掉独立索引的存储;适合'自然主键 + 整行小'的表。")


def exp8_misc(conn):
    section("实验 8:杂项验证(排序键中 rowid 的隐式参与 / DESC 索引)")
    out("复合索引末尾隐式追加 rowid:(customer_id, status, created_at, id)")
    sql = """SELECT id FROM orders
             WHERE customer_id = ? AND status = ?
             ORDER BY created_at"""
    show_plan(conn, "ORDER BY 落在索引第三列", sql, (123, "paid"))
    compare(conn, "索引序免排序", sql, (123, "paid"), repeat=100)

    sql2 = """SELECT id FROM orders
              WHERE customer_id = ?
              ORDER BY created_at DESC, status"""
    show_plan(conn, "ORDER BY 与索引序不一致", sql2, (123,))
    compare(conn, "需 TEMP B-TREE", sql2, (123,), repeat=100)

    out("\nDESC 索引可以反向满足另一方向的排序:")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_desc
                    ON orders(customer_id DESC, created_at DESC)""")
    sql3 = """SELECT id FROM orders WHERE customer_id = ?
              ORDER BY created_at DESC"""
    show_plan(conn, "DESC 索引", sql3, (123,))


def main():
    t0 = time.perf_counter()
    out(f"SQLite 版本: {sqlite3.sqlite_version}")
    out(f"数据库文件: {DB_PATH}")
    conn = build_db()
    out(f"建库+造 {N_ROWS} 行数据耗时 {(time.perf_counter()-t0):.2f} s")

    exp0_schema(conn)
    exp1_fullscan_vs_index(conn)
    exp2_composite_leftmost(conn)
    exp3_covering_index(conn)
    exp4_broken_indexes(conn)
    exp5_orderby_groupby(conn)
    exp6_analyze(conn)
    exp7_without_rowid(conn)
    exp8_misc(conn)

    section("全部实验完成")
    out(f"总耗时 {time.perf_counter()-t0:.2f} s")
    out(f"数据库保留在 {DB_PATH}")

    conn.close()
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(_out) + "\n")
    print(f"\nreport 已写入 {REPORT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
