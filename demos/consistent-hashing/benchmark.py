"""实验脚本:迁移率对比、虚拟节点扫描(负载均衡)、热点节点摘除。

运行:python benchmark.py
所有数字打印到 stdout,README 中的表格数据即来自此输出。
"""

import random
import statistics
import sys
from collections import Counter

from ring import ConsistentHashRing, ModuloRouter, EmptyRingError

KEY_COUNT = 10_000
BASE_NODES = [f"node-{i}" for i in range(10)]
TRIALS = 20  # 迁移率试验次数:vnodes 少时单次方差大,取均值才与理论可比


def _stdout_utf8() -> None:
    """Windows 控制台默认 GBK,强制 UTF-8 输出避免中文乱码。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def make_keys(n: int, seed: int = 42) -> list[str]:
    rng = random.Random(seed)
    return [f"key-{rng.randrange(10**12):012d}" for _ in range(n)]


KEYS = make_keys(KEY_COUNT)


# ---------------------------------------------------------------------------
# 实验 1:迁移率对比(10 -> 11 节点)
# ---------------------------------------------------------------------------
def experiment_migration_once(router_cls, extra_node: str, **kwargs) -> float:
    """单次试验:增加 1 个节点后需要迁移的 key 比例。"""
    r = router_cls(**kwargs)
    for n in BASE_NODES:
        r.add_node(n)
    before = {k: r.get_node(k) for k in KEYS}
    r.add_node(extra_node)
    after = {k: r.get_node(k) for k in KEYS}
    moved = sum(1 for k in KEYS if before[k] != after[k])
    return moved / KEY_COUNT


def experiment_migration(router_cls, **kwargs) -> tuple[float, float]:
    """TRIALS 次试验(换不同的新节点名),返回 (均值, 标准差)。

    vnodes=1 时环上只有 10 个点,新节点的弧长是单次抽样,方差极大;
    单次结果可能偏离理论值数倍,必须多试验取均值。
    """
    rates = [experiment_migration_once(router_cls, f"extra-{i}", **kwargs)
             for i in range(TRIALS)]
    return statistics.mean(rates), statistics.pstdev(rates)


def run_migration() -> list[tuple[str, int, float, float]]:
    rows = []
    m, s = experiment_migration(ModuloRouter)
    rows.append(("朴素取模", 0, m, s))
    for v in (1, 10, 100, 1000):
        m, s = experiment_migration(ConsistentHashRing, vnodes=v)
        rows.append(("一致性哈希", v, m, s))
    return rows


# ---------------------------------------------------------------------------
# 实验 2:虚拟节点数对负载均衡的影响(10 节点,各节点持桶分布)
# ---------------------------------------------------------------------------
def experiment_balance(vnodes: int, hasher: str = "md5") -> dict:
    r = ConsistentHashRing(hasher=hasher, vnodes=vnodes)
    for n in BASE_NODES:
        r.add_node(n)
    counts = Counter(r.get_node(k) for k in KEYS)
    vals = list(counts.values())
    expected = KEY_COUNT / len(BASE_NODES)
    return {
        "vnodes": vnodes,
        "min": min(vals),
        "max": max(vals),
        "mean": statistics.mean(vals),
        "stdev": statistics.pstdev(vals),
        "cv": statistics.pstdev(vals) / expected,  # 变异系数(相对期望值)
        "max_min_ratio": max(vals) / min(vals),
    }


def run_balance() -> list[dict]:
    return [experiment_balance(v) for v in (1, 10, 100, 1000)]


def run_balance_by_hasher() -> dict[str, list[dict]]:
    out = {}
    for h in ("md5", "fnv1a", "mmh3"):
        out[h] = [experiment_balance(v, hasher=h) for v in (1, 10, 100, 1000)]
    return out


# ---------------------------------------------------------------------------
# 实验 3:热点节点摘除 —— 受影响 key 的去向
# ---------------------------------------------------------------------------
def experiment_removal(vnodes: int) -> dict:
    r = ConsistentHashRing(vnodes=vnodes)
    for n in BASE_NODES:
        r.add_node(n)
    victim = BASE_NODES[3]  # node-3
    before = {k: r.get_node(k) for k in KEYS}
    r.remove_node(victim)
    dst = Counter()
    untouched_moved = 0
    for k in KEYS:
        new = r.get_node(k)
        if before[k] == victim:
            dst[new] += 1
        elif before[k] != new:
            untouched_moved += 1
    return {
        "vnodes": vnodes,
        "victim": victim,
        "affected": sum(dst.values()),
        "destinations": dict(dst),
        "untouched_moved": untouched_moved,
        "affected_pct": sum(dst.values()) / KEY_COUNT,
    }


def experiment_mod_removal() -> dict:
    r = ModuloRouter()
    for n in BASE_NODES:
        r.add_node(n)
    victim = BASE_NODES[3]
    before = {k: r.get_node(k) for k in KEYS}
    r.remove_node(victim)
    moved = sum(1 for k in KEYS if r.get_node(k) != before[k])
    dst = Counter(r.get_node(k) for k in KEYS if before[k] == victim)
    return {
        "victim": victim,
        "affected": KEY_COUNT - moved,  # 朴素取模:未迁移的即未受影响的
        "destinations": dict(dst),
        "untouched_moved": moved,
        "affected_pct": (KEY_COUNT - moved) / KEY_COUNT,
    }


# ---------------------------------------------------------------------------
def main() -> None:
    _stdout_utf8()
    print(f"keys={KEY_COUNT}, base_nodes={len(BASE_NODES)}, add/remove 1 node,"
          f" migration trials={TRIALS}\n")

    print("=" * 68)
    print("实验 1:迁移率(10 -> 11 节点)")
    print("=" * 68)
    print(f"{'方案':<12}{'vnodes':>8}{'迁移率(均值)':>14}{'标准差':>10}{'理论值':>10}")
    theory = {0: "~90%", **{v: "~9.1%" for v in (1, 10, 100, 1000)}}
    for name, v, mean, std in run_migration():
        print(f"{name:<12}{v:>8}{mean:>13.2%}{std:>9.2%}{theory[v]:>10}")

    print()
    print("=" * 68)
    print("实验 2:负载均衡(10 节点,10000 key,vnodes 扫描,hasher=md5)")
    print("=" * 68)
    print(f"{'vnodes':>8}{'min':>8}{'max':>8}{'mean':>10}{'stdev':>10}{'CV':>8}{'max/min':>10}")
    for row in run_balance():
        print(f"{row['vnodes']:>8}{row['min']:>8}{row['max']:>8}"
              f"{row['mean']:>10.1f}{row['stdev']:>10.1f}{row['cv']:>8.3f}"
              f"{row['max_min_ratio']:>10.2f}")

    print()
    print("实验 2b:不同哈希函数下的负载均衡(各 vnode 数的 CV / max-min)")
    for h, rows in run_balance_by_hasher().items():
        detail = "  ".join(f"v={r['vnodes']}: CV={r['cv']:.3f}" for r in rows)
        print(f"  {h:<8}{detail}")

    print()
    print("=" * 68)
    print("实验 3:摘除 node-3 后受影响 key 的去向(一致性哈希)")
    print("=" * 68)
    res1 = experiment_removal(vnodes=1)
    print(f"[vnodes=1]  受影响 key: {res1['affected']} ({res1['affected_pct']:.2%}),"
          f"其余节点被波及的 key: {res1['untouched_moved']}")
    print(f"           去向分布: {res1['destinations']}"
          f"  <- 只流向环上顺时针唯一的下一个节点")
    res100 = experiment_removal(vnodes=100)
    print(f"[vnodes=100] 受影响 key: {res100['affected']} ({res100['affected_pct']:.2%}),"
          f"其余节点被波及的 key: {res100['untouched_moved']}")
    print(f"           去向分布(被 victim 的 100 个 vnode 顺时针邻居分摊):"
          f" {res100['destinations']}")

    print()
    print("对照:朴素取模摘除 node-3")
    res = experiment_mod_removal()
    print(f"受影响 key: {res['affected']} ({res['affected_pct']:.2%}),"
          f"被无辜波及(原属其他节点但被迁移)的 key: {res['untouched_moved']}")
    print(f"原属 node-3 的 key 摘除后去向: {res['destinations']}")

    print()
    print("空环行为: ", end="")
    try:
        ConsistentHashRing().get_node("k")
    except EmptyRingError as e:
        print(f"get_node 抛出 EmptyRingError({e})")


if __name__ == "__main__":
    main()
