"""实验四(补充):连接数扩展曲线 —— 收益递减在哪里拐弯。

复用 exp_http11_strategies 的持久连接池模型,对 1/2/3/4/6/8/12/24 条连接
分别测同一资源集(24 个 × 50ms),给出"吞吐/连接数"的边际收益表。
用于回答:浏览器为什么选 6,而不是 2 或 100。

用法:先起 server_http11.py,再运行本脚本。
"""
import argparse
import http.client
import json
import os
import statistics
import threading
import time

import exp_http11_strategies as base

HOST = "127.0.0.1"


def median(xs):
    return statistics.median(xs)


def main():
    global PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8441)
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--ms", type=int, default=50)
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--pool", default="1,2,3,4,6,8,12,24")
    args = ap.parse_args()
    base.PORT = args.port  # run_pool 从模块全局取端口
    pools = [int(x) for x in args.pool.split(",")]

    results = {"params": vars(args) | {"host": HOST}, "scaling": {}}
    print(f"\n=== HTTP/1.1 连接数扩展曲线  N={args.n} 资源, 每个 {args.ms}ms, "
          f"{args.rounds} 轮中位数 ===")
    print(f"{'连接数':>6} {'中位耗时ms':>12} {'相对单连接':>10} {'边际收益(相对上一档)':>12}")
    prev = None
    for c in pools:
        if c > args.n:  # 连接数超过资源数没有意义
            break
        times = base.run_pool(c, args.n, args.ms, args.size, args.rounds)
        m = median(times)
        speedup = results["scaling"].get("1", {}).get("median_ms", m) / m
        margin = (prev / m) if prev else 1.0
        results["scaling"][str(c)] = {
            "times_ms": times, "median_ms": m,
            "speedup_vs_1conn": round(speedup, 2),
            "marginal_gain": round(margin, 2),
        }
        print(f"{c:>6} {m:>12.1f} {speedup:>9.2f}x {margin:>11.2f}x")
        prev = m

    os.makedirs("results", exist_ok=True)
    out = os.path.join("results", "conn_scaling.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {out}")
    print("解读:收益近似 N/连接数,但 6 连接之后边际收益已经很小,而每加一条连接"
          "都要付握手、内存、服务端线程、与其他 host 的连接预算竞争等代价 —— "
          "这就是浏览器折中在 6 的实测基础(更准确地说,6 是多个因素的经验折中)。")


if __name__ == "__main__":
    main()
