"""db.py — 对外 API:put / get / scan / begin / commit / rollback。

MiniDB(path) 打开(或创建)一个单文件嵌入式 KV 存储,附带 <path>.wal 日志。

事务模型(单写者,单进程):
  * 显式事务:tx = db.begin(); db.put(...); db.commit() 或 db.rollback()
  * 自动提交:不在事务中调用 put 时,自动包一层 begin/commit

原子性来源:
  * 未提交的事务只改内存页缓存,从未写盘 —— rollback 就是把脏缓存丢弃,
    断电时效果相同(进程没了 = 缓存没了)。
  * commit 采用 WAL 先行:BEGIN -> PUT(逻辑 redo 记录) -> COMMIT,
    fsync 日志后,才把脏页写数据文件,最后清空日志(checkpoint)。
    崩溃发生在任何一步,重启时重放日志都能收敛到"全部已提交事务"的状态。

恢复流程(_recover,打开时执行):
  1. 顺序扫描 WAL,遇到第一条残缺记录即停(丢弃 torn tail)
  2. 收集所有出现过 COMMIT 的事务 id
  3. 按日志顺序重放这些事务的 PUT 记录(重放即普通 B-tree 插入,幂等)
  4. 把重放后的脏页刷盘、清空 WAL
"""

import os

from pager import Pager, PAGE_SIZE, INVALID_PID
from btree import BTree
from wal import WAL, REC_BEGIN, REC_PUT, REC_COMMIT, REC_ABORT

MAX_KEY_LEN = 200
MAX_VAL_LEN = 2000   # 必须与键一起塞进一个叶子页


class DBError(Exception):
    pass


class TransactionError(DBError):
    pass


def encode_key(key):
    if isinstance(key, str):
        return key.encode("utf-8")
    if isinstance(key, (bytes, bytearray)):
        return bytes(key)
    raise DBError("key must be str or bytes, got %r" % type(key).__name__)


def encode_int(n):
    """定长 8 字节大端无符号整数键:字节序 == 数值序。"""
    if not (0 <= n < 2 ** 64):
        raise DBError("encode_int out of range: %r" % n)
    return n.to_bytes(8, "big")


def decode_int(b):
    return int.from_bytes(b, "big")


class MiniDB:
    def __init__(self, path, fsync=True):
        self.path = path
        self.wal_path = path + ".wal"
        self.fsync = fsync
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        self.pager = Pager(path)
        self.wal = WAL(self.wal_path)
        self.tree = BTree(self.pager)
        self._in_txn = False
        self._txid = 0
        self._txn_ops = []      # 本事务的 (key, value) 序列,commit 时写日志
        self._recovered_txns = 0
        self._recover()

    # ---------- 恢复 ----------

    def _recover(self):
        records = self.wal.read_records()
        committed = {txid for rtype, txid, _ in records if rtype == REC_COMMIT}
        if not committed:
            return
        for rtype, txid, payload in records:
            if rtype == REC_PUT and txid in committed:
                key, val = self._decode_put(payload)
                self.tree.insert(key, val)
        self._recovered_txns = len(committed)
        self.pager.flush_data()
        if self.fsync:
            pass  # flush_data 内部已 fsync
        self.wal.truncate()

    @staticmethod
    def _decode_put(payload):
        kl = int.from_bytes(payload[0:2], "little")
        key = payload[2:2 + kl]
        pos = 2 + kl
        vl = int.from_bytes(payload[pos:pos + 2], "little")
        val = payload[pos + 2:pos + 2 + vl]
        if len(key) != kl or len(val) != vl:
            raise DBError("corrupt PUT payload")
        return key, val

    @staticmethod
    def _encode_put(key, val):
        return len(key).to_bytes(2, "little") + key + len(val).to_bytes(2, "little") + val

    # ---------- 事务 ----------

    def begin(self):
        if self._in_txn:
            raise TransactionError("nested transactions are not supported")
        self._txid += 1
        self._in_txn = True
        self._txn_ops = []
        return self._txid

    def in_txn(self):
        return self._in_txn

    def put(self, key, value):
        kb = encode_key(key)
        vb = value.encode("utf-8") if isinstance(value, str) else bytes(value)
        if len(kb) > MAX_KEY_LEN:
            raise DBError("key too long: %d > %d bytes" % (len(kb), MAX_KEY_LEN))
        if len(vb) > MAX_VAL_LEN:
            raise DBError("value too long: %d > %d bytes" % (len(vb), MAX_VAL_LEN))
        if not self._in_txn:
            # 自动提交:单条 put 就是一个完整事务
            self.begin()
            try:
                self.tree.insert(kb, vb)
                self._txn_ops.append((kb, vb))
                self._commit_txn()
            except Exception:
                self.rollback()
                raise
        else:
            self.tree.insert(kb, vb)
            self._txn_ops.append((kb, vb))

    def get(self, key):
        kb = encode_key(key)
        v = self.tree.get(kb)
        if v is None:
            return None
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return v

    def scan(self, start=None, end=None):
        """范围扫描,产出 (key, value)。start 含端点,end 不含端点。

        键始终以 bytes 返回(str 是输入便利,但字节键无法无损还原成
        str,所以不猜测);值若为合法 UTF-8 则解码成 str,否则返回 bytes。
        """
        sb = encode_key(start) if start is not None else None
        eb = encode_key(end) if end is not None else None
        for k, v in self.tree.scan(sb, eb):
            try:
                vd = v.decode("utf-8")
            except UnicodeDecodeError:
                vd = v
            yield k, vd

    def commit(self):
        if not self._in_txn:
            raise TransactionError("no active transaction")
        self._commit_txn()

    def _commit_txn(self):
        """提交协议:先日志后数据。任何一步崩溃都可由 _recover 收敛。"""
        self.wal.append(REC_BEGIN, self._txid)
        for kb, vb in self._txn_ops:
            self.wal.append(REC_PUT, self._txid, self._encode_put(kb, vb))
        self.wal.append(REC_COMMIT, self._txid)
        if self.fsync:
            self.wal.flush()
        # WAL 已持久化:此后即使断电,重放日志也能补上数据页
        self.pager.flush_data()
        self.wal.truncate()   # checkpoint:数据已落盘,日志不再需要
        self._in_txn = False
        self._txn_ops = []

    def rollback(self):
        if not self._in_txn:
            raise TransactionError("no active transaction")
        self.wal.append(REC_ABORT, self._txid)  # 仅留痕,日志随下次 checkpoint 清空
        self.pager.discard_dirty()
        self.tree.invalidate_all()
        self._in_txn = False
        self._txn_ops = []

    # ---------- 调试/测试钩子:模拟半路断电 ----------

    def _debug_commit_wal_only(self):
        """只把日志写到 fsync,不写数据页、不清日志 —— 相当于
        进程在 commit 的"WAL 落盘、数据页未落盘"间隙被杀掉。"""
        self.wal.append(REC_BEGIN, self._txid)
        for kb, vb in self._txn_ops:
            self.wal.append(REC_PUT, self._txid, self._encode_put(kb, vb))
        self.wal.append(REC_COMMIT, self._txid)
        self.wal.flush()

    def _debug_simulate_power_loss(self):
        """丢弃内存中的未落盘状态(脏页),保留磁盘文件原样。
        之后 close 再重开,就等价于一次真实的进程死亡。"""
        self.pager.discard_dirty()
        self.tree.invalidate_all()
        self._in_txn = False
        self._txn_ops = []

    # ---------- 结构观测 ----------

    def stats(self):
        pages, leaves, internals = self.tree.stats()
        return {
            "pages": pages,
            "leaf_pages": leaves,
            "internal_pages": internals,
            "tree_height": self.tree.height(),
            "db_file_bytes": os.path.getsize(self.path) if os.path.exists(self.path) else 0,
            "wal_bytes": os.path.getsize(self.wal_path) if os.path.exists(self.wal_path) else 0,
        }

    def count(self):
        return sum(1 for _ in self.tree.items())

    def close(self):
        if self._in_txn:
            self.rollback()
        self.wal.close()
        self.pager.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
