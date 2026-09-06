"""btree.py — 以页为节点的 B+ 树。

每个节点恰好占一个 4KB 页。键为 bytes,按字节序(memcmp 序)比较;
编码器保证定长大端整数键的数值序与字节序一致。

页格式(小端):

叶子页 (type=1):
    [0]      type u8 = 1
    [1:3]    num_keys u16
    [3:7]    next_leaf u32   (指向右兄弟,INVALID_PID 表示没有 —— 范围扫描用)
    [7:]     num_keys 个 entry: klen u16 + key + vlen u16 + value

内部页 (type=2):
    [0]      type u8 = 2
    [1:3]    num_keys u16 = 分隔键个数 n
    [3:7]    first_child u32 (最左孩子)
    [7:]     n 个 entry: klen u16 + key + child u32

子树约定:children[i] 子树内所有键 < keys[i](第 i 个分隔键),
children[i+1] 子树内所有键 >= keys[i]。分隔键取右半节点(或右半
孩子子树)的最小键,因此等值查找走右分支:bisect_right(keys, k)。

分裂策略:插入后序列化超过 PAGE_SIZE 才分裂,按条目数对半切。
没有删除操作,所以不需要合并/借用,节点最小填充度不做约束。
"""

import struct
from bisect import bisect_left, bisect_right

from pager import PAGE_SIZE, INVALID_PID

LEAF = 1
INTERNAL = 2

_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")


class BTreeError(Exception):
    pass


class Node:
    __slots__ = ("pid", "leaf", "keys", "vals", "children", "next")

    def __init__(self, pid, leaf, keys=None, vals=None, children=None, nxt=INVALID_PID):
        self.pid = pid
        self.leaf = leaf
        self.keys = keys if keys is not None else []
        self.vals = vals if vals is not None else []      # 仅叶子
        self.children = children if children is not None else []  # 仅内部
        self.next = nxt                                    # 仅叶子


def serialize(node):
    out = bytearray()
    if node.leaf:
        out.append(LEAF)
        out += _U16.pack(len(node.keys))
        out += _U32.pack(node.next)
        for k, v in zip(node.keys, node.vals):
            out += _U16.pack(len(k)) + k
            out += _U16.pack(len(v)) + v
    else:
        out.append(INTERNAL)
        out += _U16.pack(len(node.keys))
        out += _U32.pack(node.children[0])
        for k, c in zip(node.keys, node.children[1:]):
            out += _U16.pack(len(k)) + k
            out += _U32.pack(c)
    return bytes(out)


def parse(pid, raw):
    leaf = raw[0] == LEAF
    (n,) = _U16.unpack_from(raw, 1)
    if leaf:
        (nxt,) = _U32.unpack_from(raw, 3)
        keys, vals = [], []
        pos = 7
        for _ in range(n):
            (kl,) = _U16.unpack_from(raw, pos); pos += 2
            keys.append(bytes(raw[pos:pos + kl])); pos += kl
            (vl,) = _U16.unpack_from(raw, pos); pos += 2
            vals.append(bytes(raw[pos:pos + vl])); pos += vl
        return Node(pid, True, keys, vals, nxt=nxt)
    else:
        (first,) = _U32.unpack_from(raw, 3)
        keys, children = [], [first]
        pos = 7
        for _ in range(n):
            (kl,) = _U16.unpack_from(raw, pos); pos += 2
            keys.append(bytes(raw[pos:pos + kl])); pos += kl
            (c,) = _U32.unpack_from(raw, pos); pos += 4
            children.append(c)
        return Node(pid, False, keys, children=children)


class BTree:
    """B+ 树。所有修改先落在 Pager 缓存,落盘时机由上层事务控制。"""

    def __init__(self, pager):
        self.pager = pager
        self.cache = {}  # pid -> Node(已解析节点缓存,回滚时整体失效)
        if pager.root_pid == INVALID_PID:
            root = Node(pager.alloc_page(), True)
            self._save(root)
            pager.root_pid = root.pid
            pager.sync_meta()
        self.root = pager.root_pid

    # ---------- 节点缓存 ----------

    def _node(self, pid):
        node = self.cache.get(pid)
        if node is None:
            node = parse(pid, self.pager.read_page(pid))
            self.cache[pid] = node
        return node

    def _save(self, node):
        data = serialize(node)
        if len(data) > PAGE_SIZE:
            raise BTreeError("node %d overflows page size (%d bytes)" % (node.pid, len(data)))
        # 页必须精确占满 PAGE_SIZE,尾部补零
        self.pager.write_page(node.pid, data + bytes(PAGE_SIZE - len(data)))
        self.cache[node.pid] = node

    def invalidate_all(self):
        """回滚后调用:内存中的节点视图不可信,全部作废。"""
        self.cache.clear()
        self.root = self.pager.root_pid

    # ---------- 点查 ----------

    def get(self, key):
        pid = self.root
        node = self._node(pid)
        while not node.leaf:
            idx = bisect_right(node.keys, key)
            node = self._node(node.children[idx])
        i = bisect_left(node.keys, key)
        if i < len(node.keys) and node.keys[i] == key:
            return node.vals[i]
        return None

    # ---------- 插入 ----------

    def insert(self, key, value):
        """插入或覆盖一个键值对(覆盖路径同样保持节点尺寸约束)。"""
        res = self._insert_rec(self.root, key, value)
        if res is not None:
            sep, right_pid = res
            old_root = self._node(self.root)
            new_root = Node(self.pager.alloc_page(), False,
                            keys=[sep], children=[old_root.pid, right_pid])
            self._save(new_root)
            self.root = new_root.pid
            self.pager.root_pid = new_root.pid
            self.pager.sync_meta()
        return True

    def _insert_rec(self, pid, key, value):
        """返回 None 表示无需上推;返回 (sep, 新右节点pid) 表示发生了分裂。"""
        node = self._node(pid)
        if node.leaf:
            i = bisect_left(node.keys, key)
            if i < len(node.keys) and node.keys[i] == key:
                node.vals[i] = value
                self._save(node)
                return None
            node.keys.insert(i, key)
            node.vals.insert(i, value)
            if len(serialize(node)) <= PAGE_SIZE:
                self._save(node)
                return None
            return self._split_leaf(node)
        else:
            i = bisect_right(node.keys, key)
            res = self._insert_rec(node.children[i], key, value)
            if res is None:
                return None
            sep, right_pid = res
            node.keys.insert(i, sep)
            node.children.insert(i + 1, right_pid)
            if len(serialize(node)) <= PAGE_SIZE:
                self._save(node)
                return None
            return self._split_internal(node)

    def _split_leaf(self, node):
        mid = len(node.keys) // 2
        right = Node(self.pager.alloc_page(), True,
                     keys=node.keys[mid:], vals=node.vals[mid:])
        node.keys = node.keys[:mid]
        node.vals = node.vals[:mid]
        right.next = node.next
        node.next = right.pid
        self._save(node)
        self._save(right)
        return right.keys[0], right.pid

    def _split_internal(self, node):
        mid = len(node.keys) // 2
        up_key = node.keys[mid]  # 中间键上推,不留在任何一侧
        right = Node(self.pager.alloc_page(), False,
                     keys=node.keys[mid + 1:], children=node.children[mid + 1:])
        node.keys = node.keys[:mid]
        node.children = node.children[:mid + 1]
        self._save(node)
        self._save(right)
        return up_key, right.pid

    # ---------- 范围扫描 ----------

    def scan(self, start=None, end=None):
        """按序产出 (key, value),start 含端点,end 不含端点,均可为 None。"""
        pid = self.root
        node = self._node(pid)
        while not node.leaf:
            idx = 0 if start is None else bisect_right(node.keys, start)
            node = self._node(node.children[idx])
        i = 0 if start is None else bisect_left(node.keys, start)
        while True:
            while i < len(node.keys):
                k = node.keys[i]
                if end is not None and k >= end:
                    return
                yield k, node.vals[i]
                i += 1
            if node.next == INVALID_PID:
                return
            node = self._node(node.next)
            i = 0

    def items(self):
        return self.scan(None, None)

    # ---------- 结构观测 ----------

    def height(self):
        if self.root == INVALID_PID:
            return 0
        h = 1
        pid = self.root
        node = self._node(pid)
        while not node.leaf:
            h += 1
            node = self._node(node.children[0])
        return h

    def stats(self):
        """返回 (页数, 叶子数, 内部节点数)。仅用于实验/调试。"""
        leaves = internals = 0
        stack = [self.root]
        while stack:
            pid = stack.pop()
            node = self._node(pid)
            if node.leaf:
                leaves += 1
            else:
                internals += 1
                stack.extend(node.children)
        return leaves + internals, leaves, internals

    def check_invariants(self):
        """校验:键有序、分隔键与子树边界一致、叶子按序链接。返回叶子链。"""
        prev_max = None
        chain = []

        def walk(pid, lo, hi):
            nonlocal prev_max
            node = self._node(pid)
            for a, b in zip(node.keys, node.keys[1:]):
                assert a < b, "keys not sorted in page %d" % pid
            for k in node.keys:
                if lo is not None:
                    assert k >= lo, "key %r < lower bound %r" % (k, lo)
                if hi is not None:
                    assert k < hi, "key %r >= upper bound %r" % (k, hi)
            if node.leaf:
                if prev_max is not None:
                    assert node.keys[0] > prev_max, "leaf chain out of order at page %d" % pid
                if node.keys:
                    prev_max = node.keys[-1]
                chain.append(pid)
            else:
                assert len(node.children) == len(node.keys) + 1, "fanout mismatch in page %d" % pid
                bounds = [lo] + node.keys + [hi]
                for i, c in enumerate(node.children):
                    walk(c, bounds[i], bounds[i + 1])
        walk(self.root, None, None)
        # DFS 中序到达的叶子序 == next 指针链接序,两条路径必须一致
        linked = []
        pid = self.root
        node = self._node(pid)
        while not node.leaf:
            node = self._node(node.children[0])
        while True:
            linked.append(node.pid)
            if node.next == INVALID_PID:
                break
            node = self._node(node.next)
        assert linked == chain, "leaf next-pointer chain does not match in-order traversal"
        return chain
