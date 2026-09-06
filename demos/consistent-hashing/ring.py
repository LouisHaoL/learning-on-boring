"""一致性哈希环 + 虚拟节点。

核心结构:sorted list of (hash_value, node) 的 vnode 点位。
get_node(key):hash(key) 后在环上顺时针找第一个 >= 该哈希的 vnode,返回其物理节点。

设计要点:
- vnode 命名 "node#i",哈希函数作用于 vnode 名而非节点名,保证散布均匀
- add/remove 用 bisect 增量插入/删除点位,不重建整环(生产上环很大)
- 环为空时 get_node 抛 EmptyRingError(显式失败优于静默吞掉)
"""

import bisect
from itertools import count

from hashers import get_hasher


class EmptyRingError(KeyError):
    """环上没有任何节点时查询抛出。"""


class ConsistentHashRing:
    def __init__(self, hasher: str = "md5", vnodes: int = 100):
        if vnodes < 1:
            raise ValueError("vnodes must be >= 1")
        self.hash = get_hasher(hasher)
        self.vnodes = vnodes
        # 两个平行数组:_points 存哈希值(供 bisect),_nodes 存对应物理节点
        self._points: list[int] = []
        self._nodes: list[str] = []
        self._ring_nodes: set[str] = set()
        self._vnode_seq = count()  # 全局递增,避免同节点重建时 vnode 名碰撞

    # ------------------------------------------------------------------
    def add_node(self, node: str) -> None:
        if node in self._ring_nodes:
            raise ValueError(f"node {node!r} already on ring")
        self._ring_nodes.add(node)
        for _ in range(self.vnodes):
            name = f"{node}#{next(self._vnode_seq)}"
            h = self.hash(name.encode())
            pos = bisect.bisect_left(self._points, h)
            self._points.insert(pos, h)
            self._nodes.insert(pos, node)

    def remove_node(self, node: str) -> None:
        if node not in self._ring_nodes:
            raise KeyError(f"node {node!r} not on ring")
        self._ring_nodes.remove(node)
        # 从右往左删,避免删除过程中的索引位移问题
        i = len(self._nodes) - 1
        while i >= 0:
            if self._nodes[i] == node:
                del self._points[i]
                del self._nodes[i]
            i -= 1

    # ------------------------------------------------------------------
    def get_node(self, key: str) -> str:
        """key 顺时针命中第一个 vnode 所属的物理节点。"""
        if not self._points:
            raise EmptyRingError("ring is empty")
        h = self.hash(key.encode())
        idx = bisect.bisect_right(self._points, h)  # 顺时针第一个 > h 的点
        if idx == len(self._points):
            idx = 0  # 绕回环起点
        return self._nodes[idx]

    # ------------------------------------------------------------------
    def nodes(self) -> set[str]:
        return set(self._ring_nodes)

    def __len__(self) -> int:
        return len(self._ring_nodes)

    def __contains__(self, node: str) -> bool:
        return node in self._ring_nodes


class ModuloRouter:
    """朴素取模路由器:node_index = hash(key) % n。同接口,便于对比。

    任何节点数量变化都会改变几乎所有 key 的归属 —— 这是迁移率实验的对照组。
    """

    def __init__(self, hasher: str = "md5", vnodes: int = 0):
        self.hash = get_hasher(hasher)
        self._ring_nodes: list[str] = []

    def add_node(self, node: str) -> None:
        if node in self._ring_nodes:
            raise ValueError(f"node {node!r} already on ring")
        self._ring_nodes.append(node)

    def remove_node(self, node: str) -> None:
        # 朴素路由通常按位置移除(保持下标连续),这里移除后其余节点前移,
        # 位置变化正是迁移率爆炸的来源
        self._ring_nodes.remove(node)

    def get_node(self, key: str) -> str:
        n = len(self._ring_nodes)
        if n == 0:
            raise EmptyRingError("ring is empty")
        idx = self.hash(key.encode()) % n
        return self._ring_nodes[idx]

    def nodes(self) -> set[str]:
        return set(self._ring_nodes)

    def __len__(self) -> int:
        return len(self._ring_nodes)

    def __contains__(self, node: str) -> bool:
        return node in self._ring_nodes
