"""实验二:HTTP/2 单连接多路复用 vs HTTP/1.1 多连接,同一资源集对照计时。

HTTP/2 侧:
  httpx.AsyncClient(http2=True)+ TLS ALPN —— 限定 max_connections=1,
  24 个并发请求全部塞进同一条连接的 24 个独立 stream,互相不阻塞。
  (用 asyncio 而非线程:HTTP/2 多路复用本质上是事件循环驱动的,
   多线程共享一条 TLS 连接在 Windows 上反而会触发非阻塞套接字冲突。)

对照(同一服务器,ALPN 同端口,客户端只降级协议):
  http/1.1 single conn   : max_connections=1、h1.1 => 串行
  http/1.1 six conns     : max_connections=6、h1.1 => 浏览器语义
  http/1.1 24 conns      : max_connections=24、h1.1 => 连接数上限放开

用法:先起 server_http2.py,再运行本脚本。
输出:耗时表 + JSON(results/http2_vs_http11.json)
"""
import argparse
import asyncio
import json
import os
import ssl
import statistics
import time

import httpx

HOST = "127.0.0.1"


def make_client(limits, http2):
    return httpx.AsyncClient(
        base_url=f"https://{HOST}:{PORT}",
        verify=SSL_CTX,
        http2=http2,
        limits=httpx.Limits(max_connections=limits,
                            max_keepalive_connections=limits),
        timeout=30,
    )


async def probe_protocol(http2):
    async with make_client(1, http2) as c:
        r = await c.get("/ping")
        return r.http_version


async def run_once(max_conns, http2, ms, size, n):
    async with make_client(max_conns, http2) as client:
        await client.get("/ping")  # 建连预热,不含入计时
        t0 = time.perf_counter()

        async def one(i):
            r = await client.get(f"/slow?ms={ms}&bytes={size}")
            await r.aread()
            assert r.status_code == 200

        await asyncio.gather(*[one(i) for i in range(n)])
        return (time.perf_counter() - t0) * 1000


def median(xs):
    return statistics.median(xs)


async def main_async(args):
    results = {"params": vars(args) | {"host": HOST}, "comparison": {}}
    scenarios = [
        ("h2_1conn_multiplexed", 1, True),
        ("h1_single_conn", 1, False),
        ("h1_six_conns", 6, False),
        ("h1_24_conns", 24, False),
    ]
    print(f"\n=== HTTP/2 vs HTTP/1.1  N={args.n} 资源, 每个延迟 {args.ms}ms, "
          f"{args.rounds} 轮取中位数 ===")
    for name, maxc, h2 in scenarios:
        proto = await probe_protocol(h2)
        times = []
        for _ in range(args.rounds):
            times.append(await run_once(maxc, h2, args.ms, args.size, args.n))
        results["comparison"][name] = {"times_ms": times, "median_ms": median(times),
                                       "negotiated_protocol": proto}
        print(f"{name:>22}: median {median(times):8.1f} ms   "
              f"(min {min(times):7.1f} / max {max(times):7.1f})   [{proto}]")

    print("\n解读:h2 用 1 条连接、24 个 stream 并行;h1.1 单连接被迫串行;"
          "h1.1 六连接 ≈ 浏览器策略(24 个资源要 4 个串行批次);"
          "24 条连接才追平 h2 单连接 —— 这正是 HTTP/2 的卖点:用一条连接换掉几十条。")
    return results


def main():
    global PORT, SSL_CTX
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8442)
    ap.add_argument("--cert", default="certs/cert.pem")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--ms", type=int, default=50)
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    PORT = args.port

    SSL_CTX = ssl.create_default_context()
    SSL_CTX.check_hostname = False
    SSL_CTX.verify_mode = ssl.CERT_NONE

    results = asyncio.run(main_async(args))

    os.makedirs("results", exist_ok=True)
    out = os.path.join("results", "http2_vs_http11.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"结果已写入 {out}")


if __name__ == "__main__":
    main()
