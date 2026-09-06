"""pager.py — 页式存储层。

数据库文件被划分为固定大小(4KB)的页,通过页 id(从 0 开始)定位,
页 pid 在文件中的偏移 = pid * PAGE_SIZE。

0 号页是元数据页:
    [0:4]   magic  b"MDB1"
    [4:8]   root_pid   u32  (B-tree 根节点页 id,INVALID_PID 表示树为空)
    [8:12]  page_count u32  (已分配页数,pid 合法区间为 [0, page_count))

缓存策略:所有读写都经过内存 cache(dict),写操作只标记 dirty,
由上层(commit 时)显式调用 flush_data() 落盘。回滚时调用
discard_dirty() 把脏页丢弃、重新从磁盘读 —— 未提交的修改从未
触碰磁盘文件,这是回滚能"免费"实现的根本原因。
"""

import os
import struct

PAGE_SIZE = 4096
META_PAGE_ID = 0
META_MAGIC = b"MDB1"
INVALID_PID = 0xFFFFFFFF


class PageError(Exception):
    pass


class Pager:
    def __init__(self, path):
        self.path = path
        existed = os.path.exists(path) and os.path.getsize(path) > 0
        self.f = open(path, "r+b" if existed else "w+b")
        self.cache = {}   # pid -> bytearray
        self.dirty = set()
        if existed:
            self._load_meta()
        else:
            self._init_meta()

    # ---------- 元数据页 ----------

    def _init_meta(self):
        buf = bytearray(PAGE_SIZE)
        buf[0:4] = META_MAGIC
        struct.pack_into("<I", buf, 4, INVALID_PID)  # root_pid
        struct.pack_into("<I", buf, 8, 1)            # page_count(0 号页自身)
        self.root_pid = INVALID_PID
        self.page_count = 1
        self.cache[META_PAGE_ID] = buf
        self.dirty.add(META_PAGE_ID)

    def _load_meta(self):
        raw = self._read_at(META_PAGE_ID)
        if raw[0:4] != META_MAGIC:
            raise PageError("bad magic in meta page: %r" % bytes(raw[0:4]))
        self.root_pid, self.page_count = struct.unpack_from("<II", raw, 4)
        self.cache[META_PAGE_ID] = raw

    def sync_meta(self):
        """把内存中的 root_pid / page_count 写回缓存中的元数据页。"""
        buf = self.cache[META_PAGE_ID]
        struct.pack_into("<I", buf, 4, self.root_pid)
        struct.pack_into("<I", buf, 8, self.page_count)
        self.dirty.add(META_PAGE_ID)

    # ---------- 页读写 ----------

    def _read_at(self, pid):
        """不经过边界检查的底层读(元数据加载时 page_count 尚未就绪)。"""
        self.f.seek(pid * PAGE_SIZE)
        data = self.f.read(PAGE_SIZE)
        if len(data) != PAGE_SIZE:
            raise PageError("short read on page %d: got %d bytes" % (pid, len(data)))
        return bytearray(data)

    def _read_raw(self, pid):
        if not (0 <= pid < self.page_count):
            raise PageError("page id out of range: %d (page_count=%d)" % (pid, self.page_count))
        return self._read_at(pid)

    def read_page(self, pid):
        page = self.cache.get(pid)
        if page is None:
            page = self._read_raw(pid)
            self.cache[pid] = page
        return page

    def write_page(self, pid, data):
        if len(data) != PAGE_SIZE:
            raise PageError("page %d must be exactly %d bytes, got %d" % (pid, PAGE_SIZE, len(data)))
        self.cache[pid] = bytearray(data)
        self.dirty.add(pid)

    def alloc_page(self):
        """分配一个新页 id(不落盘,内容由调用方随后 write_page)。"""
        pid = self.page_count
        self.page_count += 1
        self.sync_meta()  # page_count 变了,元数据页变脏
        return pid

    # ---------- 落盘 / 回滚 ----------

    def flush_data(self):
        """把所有脏页写入数据文件并 fsync。调用前提:WAL 已 fsync。"""
        for pid in sorted(self.dirty):
            self.f.seek(pid * PAGE_SIZE)
            self.f.write(self.cache[pid])
        self.f.flush()
        os.fsync(self.f.fileno())
        self.dirty.clear()

    def discard_dirty(self):
        """丢弃所有未落盘的修改(回滚 / 模拟断电),恢复到磁盘状态。"""
        for pid in self.dirty:
            self.cache.pop(pid, None)
        self.dirty.clear()
        # 元数据(根指针、页数)以磁盘为准
        self._load_meta()
        # page_count 可能缩小,清掉越界缓存
        for pid in [p for p in self.cache if p >= self.page_count]:
            del self.cache[pid]

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass
