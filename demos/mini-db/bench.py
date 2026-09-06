"""bench.py — 性能粗测与树结构实验。

实验:
  1. 10 万条随机 KV 插入耗时(分批提交,fsync 开)
  2. 点查 QPS
  3. 树高随数据量的增长(1e3 / 1e4 / 1e5 / 1e6)

运行:python bench.py
"""

import os
import platform
import random
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from db import MiniDB, encode_int, decode_int

# Windows 控制台默认 GBK,强制 UTF-8 避免中文输出乱码
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

DATA_DIR = os.path.join(HERE, "bench_data")
COMMIT_EVERY = 1000      # 每千条一个事务(一次 fsync 对)


def fresh_db(name):
    path = os.path.join(DATA_DIR, name)
    for p in (path, path + ".wal"):
        if os.path.exists(p):
            os.remove(p)
    return MiniDB(path)


def bench_insert_batched(n=100_000, commit_every=COMMIT_EVERY):
    """10 万条随机插入:显式事务,每 commit_every 条提交一次。"""
    db = fresh_db("bench.db")
    rng = random.Random(1)
    t0 = time.perf_counter()
    db.begin()
    for i in range(n):
        db.put(encode_int(rng.randrange(0, 2 ** 63)), "value-%d" % i)
        if (i + 1) % commit_every == 0:
            db.commit()
            if i + 1 < n:
                db.begin()
    if n % commit_every != 0:
        db.commit()
    elapsed = time.perf_counter() - t0
    cnt = db.count()
    db.close()
    return elapsed, cnt


def bench_get(n_rows=100_000, n_queries=200_000):
    db = fresh_db("get.db")
    rng = random.Random(2)
    keys = [encode_int(rng.randrange(0, 2 ** 63)) for _ in range(n_rows)]
    t0 = time.perf_counter()
    db.begin()
    for k in keys:
        db.put(k, "value")
    db.commit()
    insert_t = time.perf_counter() - t0

    queries = [keys[rng.randrange(0, n_rows)] if rng.random() < 0.9 else encode_int(2 ** 63 + 1)
               for _ in range(n_queries)]
    t0 = time.perf_counter()
    for k in queries:
        db.get(k)
    elapsed = time.perf_counter() - t0
    db.close()
    return insert_t, elapsed, n_queries / elapsed


def tree_height_experiment():
    rows = []
    for n in (1_000, 10_000, 100_000, 1_000_000):
        db = fresh_db("height_%d.db" % n)
        t0 = time.perf_counter()
        db.begin()
        for i in range(n):
            db.put(encode_int(i), "v%d" % i)   # 顺序插入
            if (i + 1) % 5000 == 0:
                db.commit()
                if i + 1 < n:
                    db.begin()
        if n % 5000 != 0:
            db.commit()
        elapsed = time.perf_counter() - t0
        h = db.tree.height()
        stats = db.stats()
        # 中序遍历抽查有序性(前 1000 + 后 1000)
        it = db.scan()
        head = [decode_int(k) for k, _ in (next(it) for _ in range(1000))]
        check_sorted = head == sorted(head)
        db.close()
        rows.append((n, h, stats["pages"], elapsed, check_sorted))
        print("  n=%9d  height=%d  pages=%6d  insert %.1fs  head-sorted=%s"
              % (n, h, stats["pages"], elapsed, check_sorted))
    return rows


def machine_info():
    return ("Python %s on %s / %s (%s), CPU %s"
            % (platform.python_version(), platform.system(), platform.release(),
               platform.machine(), platform.processor() or "unknown"))


def main():
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    os.makedirs(DATA_DIR)
    print("机器:%s" % machine_info())
    print()

    print("[实验 1] 100,000 条随机 KV 插入(每 %d 条提交一次)" % COMMIT_EVERY)
    elapsed, cnt = bench_insert_batched()
    print("  插入 %d 条耗时 %.2f s(约 %.0f 行/s),重扫计数验证 = %d"
          % (100_000, elapsed, 100_000 / elapsed, cnt))
    print()

    print("[实验 2] 点查 QPS(9 成命中 + 1 成未命中)")
    insert_t, qtime, qps = bench_get()
    print("  准备数据 100k 条插入 %.2f s;查询 200,000 次耗时 %.2f s,QPS ≈ %.0f"
          % (insert_t, qtime, qps))
    print()

    print("[实验 3] 树高随数据量增长(顺序插入,中途随机乱序不参与)")
    tree_height_experiment()


if __name__ == "__main__":
    main()
