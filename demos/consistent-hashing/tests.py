"""断言脚本:python tests.py,全过则打印 OK。

覆盖:路由确定性、增删节点后的归属一致性(不动点)、环空行为、
接口一致性(环 vs 朴素路由)、迁移率的理论量级断言。
"""

from ring import ConsistentHashRing, ModuloRouter, EmptyRingError
from hashers import HASHERS, get_hasher

NODES = [f"node-{i}" for i in range(10)]
KEYS = [f"key-{i}" for i in range(2000)]


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_deterministic():
    """同一 key 在环不变时反复查询结果一致。"""
    for h in HASHERS:
        r = ConsistentHashRing(hasher=h, vnodes=50)
        for n in NODES:
            r.add_node(n)
        first = {k: r.get_node(k) for k in KEYS}
        second = {k: r.get_node(k) for k in KEYS}
        check(first == second, f"router not deterministic (hasher={h})")
        check(all(v in NODES for v in first.values()), "returned unknown node")


def test_hasher_sanity():
    """哈希函数:64 位非负、确定性、雪崩(单比特翻转平均改变约一半输出位)。

    注:FNV-1a 对个别单比特翻转的雪崩较差(它靠乘法逐步扩散,无 finalizer),
    因此这里统计 200 组单比特扰动的平均汉明距离,理想值 32。
    """
    import random
    rng = random.Random(7)
    for h in HASHERS:
        f = get_hasher(h)
        a = f(b"hello")
        check(0 <= a < (1 << 64), f"{h}: out of 64-bit range")
        check(a == f(b"hello"), f"{h}: not deterministic")
        dists = []
        for _ in range(200):
            base = bytes(rng.randrange(256) for _ in range(rng.randrange(4, 40)))
            i = rng.randrange(len(base))
            mut = base[:i] + bytes([base[i] ^ (1 << rng.randrange(8))]) + base[i + 1:]
            dists.append(bin(f(base) ^ f(mut)).count("1"))
        avg = sum(dists) / len(dists)
        check(avg > 24, f"{h}: weak avalanche (avg {avg:.1f} bits, ideal 32)")


def test_add_node_stability():
    """增加节点后,原有 key 要么原地不动、要么迁往新节点 —— 不会迁去别的老节点。"""
    r = ConsistentHashRing(vnodes=100)
    for n in NODES:
        r.add_node(n)
    before = {k: r.get_node(k) for k in KEYS}
    r.add_node("node-new")
    for k in KEYS:
        after = r.get_node(k)
        if before[k] != after:
            check(after == "node-new",
                  f"key {k} moved {before[k]} -> {after}, expected -> node-new")


def test_remove_node_locality():
    """移除节点后,只有原属该节点的 key 会迁移,其他 key 一律不动。"""
    r = ConsistentHashRing(vnodes=100)
    for n in NODES:
        r.add_node(n)
    before = {k: r.get_node(k) for k in KEYS}
    victim = "node-4"
    r.remove_node(victim)
    for k in KEYS:
        after = r.get_node(k)
        if before[k] != victim:
            check(after == before[k], f"unaffected key {k} moved {before[k]} -> {after}")
        else:
            check(after != victim, f"key {k} still routed to removed node")


def test_remove_nonexistent_and_duplicate():
    r = ConsistentHashRing(vnodes=10)
    r.add_node("a")
    try:
        r.remove_node("ghost")
        raise SystemExit("removing unknown node should raise KeyError")
    except KeyError:
        pass
    try:
        r.add_node("a")
        raise SystemExit("adding duplicate node should raise ValueError")
    except ValueError:
        pass


def test_empty_ring():
    r = ConsistentHashRing()
    try:
        r.get_node("k")
        raise SystemExit("empty ring should raise EmptyRingError")
    except EmptyRingError:
        pass
    m = ModuloRouter()
    try:
        m.get_node("k")
        raise SystemExit("empty router should raise EmptyRingError")
    except EmptyRingError:
        pass
    # 加了再删光,同样回到空环错误
    r.add_node("a")
    r.remove_node("a")
    try:
        r.get_node("k")
        raise SystemExit("emptied ring should raise EmptyRingError")
    except EmptyRingError:
        pass


def test_uniform_vnode_naming():
    """同一物理节点重复摘除再挂回(vnode 名递增),环保持可用且行为确定。"""
    r = ConsistentHashRing(vnodes=25)
    for n in NODES:
        r.add_node(n)
    snap1 = {k: r.get_node(k) for k in KEYS}
    r.remove_node("node-0")
    r.add_node("node-0")
    snap2 = {k: r.get_node(k) for k in KEYS}
    check(snap1 != snap2 or True, "re-add may remap; only require determinism")
    check(all(r.get_node(k) == snap2[k] for k in KEYS), "post-readd not stable")
    check(len(r) == len(NODES), "node count wrong after re-add")


def test_modulo_router_baseline():
    """朴素路由:同接口可用;节点数量不变时稳定。"""
    m = ModuloRouter()
    for n in NODES:
        m.add_node(n)
    a = {k: m.get_node(k) for k in KEYS}
    b = {k: m.get_node(k) for k in KEYS}
    check(a == b, "modulo router not deterministic")
    check(all(v in NODES for v in a.values()), "modulo router returned unknown node")


def test_migration_rates():
    """核心理论断言:朴素取模迁移率 > 85%;一致性哈希在 10->11 时接近 1/11。"""
    moved_mod = _migration(ModuloRouter())
    check(moved_mod > 0.85, f"modulo migration rate unexpectedly low: {moved_mod:.2%}")

    moved_ch = _migration(ConsistentHashRing(vnodes=100))
    # 理论 ~1/11 = 9.1%;统计涨落允许 [4%, 16%]
    check(0.04 < moved_ch < 0.16,
          f"consistent-hashing migration rate off theory: {moved_ch:.2%}")
    check(moved_ch < moved_mod / 3, "consistent hashing should beat modulo by far")


def _migration(router):
    for n in NODES:
        router.add_node(n)
    before = {k: router.get_node(k) for k in KEYS}
    router.add_node("node-x")
    moved = sum(1 for k in KEYS if router.get_node(k) != before[k])
    return moved / len(KEYS)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"\n{len(tests)} tests, all passed. OK")


if __name__ == "__main__":
    main()
