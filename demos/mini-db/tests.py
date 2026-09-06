"""tests.py — mini-db 断言测试套件。

覆盖:基本 KV 读写、范围扫描、事务提交/回滚、B-tree 不变量、
持久性、以及三类崩溃恢复场景(WAL 已提交未落盘 / WAL 尾部撕裂 /
纯未提交事务),另含一个真实子进程死亡测试。

运行:python tests.py
"""

import os
import random
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import MiniDB, encode_int, decode_int, DBError

# Windows 控制台默认 GBK,强制 UTF-8 避免中文输出乱码
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp_tests")

_passed = 0


def setup():
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)


def dbfile(name):
    return os.path.join(TMP, name)


def check(cond, msg):
    global _passed
    assert cond, msg
    _passed += 1


# ---------------------------------------------------------------- 基础功能

def test_basic_kv():
    db = MiniDB(dbfile("basic.db"))
    db.put("name", "claude")
    db.put("lang", "python")
    check(db.get("name") == "claude", "get str")
    check(db.get("missing") is None, "get missing -> None")
    db.put("name", "updated")  # 覆盖
    check(db.get("name") == "updated", "overwrite")
    # bytes 值(非 UTF-8)原样返回
    db.put(b"bin", bytes([0xFF, 0xFE]))
    check(db.get(b"bin") == bytes([0xFF, 0xFE]), "binary value roundtrip")
    # 键/值超限应报错
    try:
        db.put("k" * 201, "v")
        check(False, "oversize key must raise")
    except DBError:
        check(True, "oversize key raises")
    try:
        db.put("k", "v" * 2001)
        check(False, "oversize value must raise")
    except DBError:
        check(True, "oversize value raises")
    db.close()


def test_scan():
    db = MiniDB(dbfile("scan.db"))
    for i in range(500):
        db.put(encode_int(i), "v%d" % i)
    keys = [decode_int(k) for k, _ in db.scan()]
    check(keys == list(range(500)), "full scan sorted & complete")
    keys = [decode_int(k) for k, _ in db.scan(encode_int(100), encode_int(110))]
    check(keys == list(range(100, 110)), "range scan [100,110)")
    keys = [decode_int(k) for k, _ in db.scan(encode_int(495))]
    check(keys == list(range(495, 500)), "open-ended scan")
    db.close()


def test_txn_commit_rollback():
    db = MiniDB(dbfile("txn.db"))
    db.put("a", "1")
    db.begin()
    db.put("b", "2")
    db.put("c", "3")
    check(db.get("b") == "2", "read-own-writes inside txn")
    db.rollback()
    check(db.get("b") is None and db.get("c") is None, "rollback discards")
    check(db.get("a") == "1", "committed data intact after rollback")
    db.begin()
    db.put("b", "2")
    db.commit()
    check(db.get("b") == "2", "commit persists")
    # 事务内覆盖旧值,回滚后应恢复旧值
    db.begin()
    db.put("a", "999")
    db.rollback()
    check(db.get("a") == "1", "overwrite rolled back")
    # 嵌套事务应拒绝
    db.begin()
    try:
        db.begin()
        check(False, "nested txn must raise")
    except DBError:
        check(True, "nested txn raises")
    db.rollback()
    try:
        db.commit()
        check(False, "commit without txn must raise")
    except DBError:
        check(True, "stray commit raises")
    db.close()


def test_random_stress_vs_dict():
    """随机插入后与内存 dict 逐项对比 + 中序遍历 + 树不变量。"""
    db = MiniDB(dbfile("stress.db"))
    rng = random.Random(20260906)
    ref = {}
    db.begin()
    for n in range(3300):
        k = encode_int(rng.randrange(0, 100000))
        v = "val-%d" % rng.randrange(0, 10 ** 9) if n < 3000 else "overwritten"
        db.put(k, v)
        ref[k] = v
        if (n + 1) % 1000 == 0:
            db.commit()
            if n + 1 < 3300:
                db.begin()
    if 3300 % 1000 != 0:
        db.commit()
    check(db.count() == len(ref), "row count matches dict")
    items = list(db.scan())
    check([k for k, _ in items] == sorted(ref.keys()), "in-order traversal sorted")
    check(dict(items) == ref, "full content matches dict")
    # 点查抽样
    for k in rng.sample(sorted(ref), 100):
        check(db.get(k) == ref[k], "point lookup %r" % k)
    check(db.get(encode_int(999999)) is None, "absent key")
    db.tree.check_invariants()
    db.close()
    # 重开再验一遍(经过落盘+重载路径)
    db = MiniDB(dbfile("stress.db"))
    check(dict(db.scan()) == ref, "content survives reopen")
    db.tree.check_invariants()
    db.close()


def test_persistence_reopen():
    db = MiniDB(dbfile("persist.db"))
    for i in range(100):
        db.put(encode_int(i), "v%d" % i)
    db.close()
    db = MiniDB(dbfile("persist.db"))
    check(db.count() == 100, "100 rows after reopen")
    check(db.get(encode_int(50)) == "v50", "value after reopen")
    db.close()


# ---------------------------------------------------------------- 崩溃恢复

def test_crash_wal_flushed_data_not():
    """commit 走到『WAL 已 fsync、数据页未落盘』时断电:
    重启重放 WAL,已提交数据必须补齐。"""
    db = MiniDB(dbfile("crash1.db"))
    db.put(encode_int(1), "committed-before")
    db.begin()
    for i in range(2, 102):
        db.put(encode_int(i), "committed-crash-txn")
    db._debug_commit_wal_only()
    db._debug_simulate_power_loss()
    db.close()
    check(os.path.getsize(dbfile("crash1.db.wal")) > 0, "WAL left on disk after crash")
    db = MiniDB(dbfile("crash1.db"))
    check(db._recovered_txns == 1, "exactly 1 txn replayed")
    check(db.count() == 101, "all 101 committed rows recovered")
    check(db.get(encode_int(1)) == "committed-before", "pre-crash row intact")
    check(db.get(encode_int(101)) == "committed-crash-txn", "replayed row intact")
    check(os.path.getsize(dbfile("crash1.db.wal")) == 0, "WAL truncated after recovery")
    # 恢复结果本身要可再持久化
    db.close()
    db = MiniDB(dbfile("crash1.db"))
    check(db.count() == 101, "recovered data stable across another reopen")
    db.close()


def test_crash_torn_wal_tail():
    """COMMIT 记录被撕掉一半:该事务必须整体丢失,之前的数据完好。
    这是 Write-Ahead + CRC 校验的意义所在。"""
    db = MiniDB(dbfile("crash2.db"))
    for i in range(10):
        db.put(encode_int(i), "committed")
    db.begin()
    for i in range(10, 20):
        db.put(encode_int(i), "torn-txn")
    db._debug_commit_wal_only()
    db._debug_simulate_power_loss()
    db.close()
    wal_size = os.path.getsize(dbfile("crash2.db.wal"))
    check(wal_size > 0, "WAL non-empty before tearing")
    with open(dbfile("crash2.db.wal"), "r+b") as f:
        f.truncate(wal_size - 6)  # 撕掉 COMMIT 记录的尾部(含 CRC)
    db = MiniDB(dbfile("crash2.db"))
    check(db.count() == 10, "torn txn entirely lost, committed rows intact")
    check(db.get(encode_int(19)) is None, "no row from torn txn")
    check(db.get(encode_int(9)) == "committed", "pre-crash rows intact")
    db.close()


def test_crash_uncommitted_lost():
    """BEGIN/PUT 都在日志里但没有 COMMIT:事务不算数。"""
    db = MiniDB(dbfile("crash3.db"))
    db.put(encode_int(1), "committed")
    db.begin()
    db.put(encode_int(2), "never-committed")
    db._debug_simulate_power_loss()  # 连 WAL 都还没写
    db.close()
    db = MiniDB(dbfile("crash3.db"))
    check(db.count() == 1, "only committed row survives")
    check(db.get(encode_int(2)) is None, "uncommitted row lost")
    db.close()


CHILD_CODE = r"""
import os, sys
sys.path.insert(0, {pkg!r})
from db import MiniDB, encode_int
db = MiniDB({dbpath!r})
db.begin()
for i in range(5):                      # 第一批:正常提交
    db.put(encode_int(i), "committed")
db.commit()
print("COMMITTED batch1", flush=True)
db.begin()                              # 第二批:写到一半直接 os._exit
for i in range(5, 500):
    db.put(encode_int(i), "uncommitted")
    if i == 250:
        os._exit(1)                     # 模拟进程被杀,什么清理都不做
db.commit()
""".format(pkg=os.path.dirname(os.path.abspath(__file__)), dbpath=dbfile("crash4.db"))


def test_crash_real_process_death():
    """真实子进程:commit 一批后,在未提交事务中途 os._exit(1)。"""
    r = subprocess.run([sys.executable, "-c", CHILD_CODE],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode != 0, "child died abnormally as intended")
    check("COMMITTED batch1" in r.stdout, "child committed batch1 before dying")
    db = MiniDB(dbfile("crash4.db"))
    check(db.count() == 5, "only the committed batch survives process death")
    for i in range(5):
        check(db.get(encode_int(i)) == "committed", "committed row %d intact" % i)
    check(db.get(encode_int(250)) is None, "uncommitted row lost")
    check(db.get(encode_int(499)) is None, "uncommitted row lost (end)")
    db.close()


# ---------------------------------------------------------------- 树结构

def test_tree_shape_and_splits():
    """树高随数据量增长;大量随机插入后中序遍历与去重集合完全一致。"""
    db = MiniDB(dbfile("shape.db"))
    heights = {}
    rng = random.Random(7)
    ref = set()
    for n in (1000, 5000, 20000):
        db.begin()
        puts_in_txn = 0
        while len(ref) < n:
            k = encode_int(rng.randrange(0, n * 10))
            if k in ref:
                continue
            ref.add(k)
            db.put(k, "v")
            puts_in_txn += 1
            if puts_in_txn % 1000 == 0:
                db.commit()
                db.begin()
        db.commit()
        db.tree.check_invariants()
        h = db.tree.height()
        heights[n] = h
        check(db.count() == len(ref), "count at n=%d" % n)
    # O(内部节点条目数) 量级增长:1e3 -> 2e4 最多涨 2~3 层
    check(heights[20000] >= heights[1000], "height non-decreasing")
    check(heights[20000] - heights[1000] <= 3, "height grows logarithmically")
    check(dict(db.scan()).keys() == ref, "final traversal matches inserted set")
    db.close()
    print("    tree heights:", heights)


# ----------------------------------------------------------------

def main():
    setup()
    tests = [
        test_basic_kv,
        test_scan,
        test_txn_commit_rollback,
        test_random_stress_vs_dict,
        test_persistence_reopen,
        test_crash_wal_flushed_data_not,
        test_crash_torn_wal_tail,
        test_crash_uncommitted_lost,
        test_crash_real_process_death,
        test_tree_shape_and_splits,
    ]
    for t in tests:
        print("[RUN ] %s" % t.__name__)
        t()
        print("[PASS] %s" % t.__name__)
    print("\nAll %d checks in %d tests passed." % (_passed, len(tests)))


if __name__ == "__main__":
    main()
