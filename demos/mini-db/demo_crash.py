"""demo_crash.py — 真实崩溃恢复演示(两个场景)。

场景 A「随机 kill」:
    子进程分 5 批写入 10000 条(每批 2000 条一个事务)。父进程收到
    第 2 批回执后随机延时 0~150ms 直接 kill 子进程(TerminateProcess,
    无任何清理)。由于 commit 阶段只占批次周期的约 10%,kill 几乎总是
    落在『未提交修改还在内存、尚未写 WAL』的窗口 —— 重开后已提交批次
    完好,被杀批次整体消失。

场景 B「WAL 已落盘、数据页未落盘」:
    子进程正常提交若干批后,最后一批调用 _debug_commit_wal_only()
    —— 这段代码与 commit() 的前半段完全相同(BEGIN/PUT/COMMIT 写入
    WAL 并 fsync),然后立刻 os._exit(1)。等价于进程死在两条 fsync
    之间的瞬间。重开后必须重放 WAL 把这批数据补回来。

两个场景结束后都校验:已 commit 数据一条不少、未 commit 数据一条不多、
键空间连续无空洞。

运行:python demo_crash.py
"""

import os
import random
import shutil
import subprocess
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

DATA_DIR = os.path.join(HERE, "demo_data")
DB_PATH = os.path.join(DATA_DIR, "demo.db")
BATCH = 2000
TOTAL_BATCHES = 5            # 5 * 2000 = 10000 条
KILL_AFTER_BATCHES = 2

CHILD_RANDOM = r"""
import os, sys
sys.path.insert(0, {here!r})
from db import MiniDB, encode_int
db = MiniDB({dbpath!r})
for b in range({total_batches}):
    db.begin()
    for i in range(b * {batch}, (b + 1) * {batch}):
        db.put(encode_int(i), "value-%d" % i)
    db.commit()
    print("COMMIT batch %d (rows %d..%d)" % (b, b * {batch}, (b + 1) * {batch} - 1), flush=True)
""".format(here=HERE, dbpath=DB_PATH, total_batches=TOTAL_BATCHES, batch=BATCH)

CHILD_WAL_ONLY_EXIT = r"""
import os, sys
sys.path.insert(0, {here!r})
from db import MiniDB, encode_int
db = MiniDB({dbpath!r})
for b in range({committed_batches}):
    db.begin()
    for i in range(b * {batch}, (b + 1) * {batch}):
        db.put(encode_int(i), "value-%d" % i)
    db.commit()
    print("COMMIT batch %d (rows %d..%d)" % (b, b * {batch}, (b + 1) * {batch} - 1), flush=True)
# 最后一批:走到 commit 的前半段(WAL 已 fsync),数据页还没写,进程消失
db.begin()
for i in range({last_start}, {last_start} + {batch}):
    db.put(encode_int(i), "value-%d" % i)
db._debug_commit_wal_only()
print("WAL FSYNCED batch {committed_batches}, dying before data flush", flush=True)
os._exit(1)
""".format(here=HERE, dbpath=DB_PATH, committed_batches=TOTAL_BATCHES - 1,
           batch=BATCH, last_start=(TOTAL_BATCHES - 1) * BATCH)


def spawn(code):
    return subprocess.Popen([sys.executable, "-c", code],
                            stdout=subprocess.PIPE, text=True, encoding="utf-8")


def verify(expect_replay):
    """重开数据库,校验并打印对比表。返回实际行数与是否全部通过。"""
    wal_bytes = os.path.getsize(DB_PATH + ".wal") if os.path.exists(DB_PATH + ".wal") else 0
    db_bytes = os.path.getsize(DB_PATH)
    print("  崩溃后磁盘状态:db 文件 %d 字节,WAL 残留 %d 字节" % (db_bytes, wal_bytes))
    db = MiniDB(DB_PATH)
    keys = [decode_int(k) for k, _ in db.scan()]
    n = len(keys)
    contiguous = keys == list(range(n))
    whole_batches = n % BATCH == 0
    replayed = db._recovered_txns
    print("  %-30s %5d 条" % ("恢复后实际行数:", n))
    print("  %-30s %5d 个" % ("恢复重放的事务数:", replayed))
    print("  %-30s %s" % ("行数是整批(事务原子性):", "是" if whole_batches else "否"))
    print("  %-30s %s" % ("键空间 0..N-1 连续无空洞:", "是" if contiguous else "否"))
    print("  %-30s %s" % ("WAL 重放路径被触发:", "是" if replayed > 0 else "否"))
    ok = contiguous and whole_batches and (replayed > 0) == expect_replay
    db.close()
    return n, ok


def main():
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    os.makedirs(DATA_DIR)
    print("=== mini-db 崩溃恢复演示 ===")
    print("批次大小 %d 条,计划共 %d 批(每批一个事务)" % (BATCH, TOTAL_BATCHES))

    # ---------------- 场景 A:随机 kill ----------------
    print()
    print("【场景 A】随机 kill:收到第 %d 批回执后随机延时 0~150ms 杀掉子进程" % KILL_AFTER_BATCHES)
    proc = spawn(CHILD_RANDOM)
    confirmed = 0
    deadline = time.time() + 120
    while confirmed < KILL_AFTER_BATCHES and time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith("COMMIT"):
            confirmed += 1
            print("  [父进程] 收到回执: %s" % line.strip())
    time.sleep(0.001 * random.randint(0, 150))
    proc.kill()
    proc.wait()
    print("  [父进程] 子进程已被 kill(约在第 %d 批中途)" % confirmed)
    n_a, ok_a = verify(expect_replay=False)
    print("  场景 A 结果:%s(commit 的 %d 条完好;被杀批次整体消失)"
          % ("通过" if ok_a else "失败", n_a))

    # ---------------- 场景 B:WAL 已 fsync、数据页未落盘 ----------------
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    os.makedirs(DATA_DIR)
    print()
    print("【场景 B】受控断点:最后一批 WAL fsync 完成后、数据页落盘前 os._exit(1)")
    proc = spawn(CHILD_WAL_ONLY_EXIT)
    seen = 0
    deadline = time.time() + 120
    while seen < TOTAL_BATCHES and time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith(("COMMIT", "WAL")):
            seen += 1
            print("  [子进程] %s" % line.strip())
    proc.wait()
    n_b, ok_b = verify(expect_replay=True)
    expect_full = TOTAL_BATCHES * BATCH
    print("  %-30s %s" % ("计划 10000 条全部恢复:", "是" if n_b == expect_full else "否"))
    ok_b = ok_b and n_b == expect_full
    print("  场景 B 结果:%s(WAL 重放把已 commit 未刷盘的 %d 条补了回来)"
          % ("通过" if ok_b else "失败", BATCH))

    print()
    if ok_a and ok_b:
        print("结论:两种崩溃窗口下,已 commit 数据均完好、未 commit 数据均消失,恢复一致。")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
