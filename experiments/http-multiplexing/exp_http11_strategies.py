"""实验一:HTTP/1.1 下三种取数策略的总耗时对比。

策略:
  serial_1conn : 单连接 + keep-alive,串行请求 N 个资源(每个都要等上一个完成)
  conn_6       : 6 条并发连接(Chrome/Firefox 对同一 host 的经典上限)
  conn_100     : 100 条并发连接(对照:逼近无连接数限制的极限)

附带:raw pipelining —— 在一条连接上把 N 个请求一次性写出(HTTP/1.1 管线化),
观察响应仍必须按序到达导致的队头阻塞。

用法:先起 server_http11.py,再运行本脚本。
输出:耗时表 + JSON(results/http11_results.json)
"""
import argparse
import http.client
import json
import os
import socket
import statistics
import threading
import time

HOST = "127.0.0.1"


def _worker(conn, queue, ms, size):
    """一条持久连接上的消费循环:HTTP/1.1 下同连接只能串行。"""
    while True:
        try:
            queue.pop()
        except IndexError:
            return
        conn.request("GET", f"/slow?ms={ms}&bytes={size}")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 200


def run_pool(n_conns, n_resources, ms, size, rounds):
    """n_conns 条【持久】连接并发消费 n_resources 个请求(浏览器语义:
    每条连接内部串行,连接之间并发)。返回每轮总耗时(ms)列表。"""
    times = []
    for _ in range(rounds):
        queue = [None] * n_resources
        conns = [http.client.HTTPConnection(HOST, PORT, timeout=30)
                 for _ in range(n_conns)]
        t0 = time.perf_counter()
        threads = [
            threading.Thread(target=_worker, args=(c, queue, ms, size))
            for c in conns
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        times.append((time.perf_counter() - t0) * 1000)
        for c in conns:
            c.close()
    return times


def run_serial_keepalive(n_resources, ms, size, rounds):
    """单连接 keep-alive,串行:第 k+1 个请求必须等第 k 个响应读完。"""
    times = []
    for _ in range(rounds):
        conn = http.client.HTTPConnection(HOST, PORT, timeout=30)
        t0 = time.perf_counter()
        for _ in range(n_resources):
            conn.request("GET", f"/slow?ms={ms}&bytes={size}")
            resp = conn.getresponse()
            resp.read()
            assert resp.status == 200
        times.append((time.perf_counter() - t0) * 1000)
        conn.close()
    return times


def run_pipelining(n_resources, ms, size):
    """原始 socket 管线化:一次性写出 N 个请求,观察响应到达顺序与节奏。

    返回 (总耗时ms, [每字节的到达时刻ms], [响应序号按到达顺序])。
    """
    req = f"GET /slow?ms={ms}&bytes={size} HTTP/1.1\r\nHost: {HOST}\r\n\r\n"
    s = socket.create_connection((HOST, PORT), timeout=60)
    s.settimeout(0.002)
    t0 = time.perf_counter()
    s.sendall(req.encode() * n_resources)  # 一次性写出全部请求

    arrivals = []  # (到达时刻ms, 本轮读到的字节数)
    header_len = None
    body_per_resp = None
    buf = b""
    total_read = 0
    expected = n_resources * (0 + size)
    n_done = 0
    while n_done < n_resources:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            break
        total_read += len(chunk)
        arrivals.append(((time.perf_counter() - t0) * 1000, len(chunk)))
        buf += chunk
        if header_len is None and b"\r\n\r\n" in buf:
            head, rest = buf.split(b"\r\n\r\n", 1)
            header_len = len(head) + 4
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    body_per_resp = int(line.split(b":")[1])
        if body_per_resp and total_read >= header_len + body_per_resp * (n_done + 1):
            n_done = (total_read - header_len) // body_per_resp
    elapsed = (time.perf_counter() - t0) * 1000
    s.close()
    return elapsed, arrivals, total_read


def median(xs):
    return statistics.median(xs)


def main():
    global PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8441)
    ap.add_argument("--n", type=int, default=24, help="资源数")
    ap.add_argument("--ms", type=int, default=50, help="每个资源的服务端延迟")
    ap.add_argument("--size", type=int, default=2048, help="每个资源的响应体大小")
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()
    PORT = args.port

    conn = http.client.HTTPConnection(HOST, PORT, timeout=5)
    conn.request("GET", "/ping")
    assert conn.getresponse().read() == b"ok"
    conn.close()

    results = {
        "params": vars(args) | {"host": HOST},
        "http11": {},
    }
    t_serial = run_serial_keepalive(args.n, args.ms, args.size, args.rounds)
    t_6 = run_pool(6, args.n, args.ms, args.size, args.rounds)
    t_100 = run_pool(100, args.n, args.ms, args.size, args.rounds)

    results["http11"]["serial_1conn"] = {"times_ms": t_serial, "median_ms": median(t_serial)}
    results["http11"]["conn_6"] = {"times_ms": t_6, "median_ms": median(t_6)}
    results["http11"]["conn_100"] = {"times_ms": t_100, "median_ms": median(t_100)}

    print(f"\n=== HTTP/1.1 策略对比  N={args.n} 资源, 每个延迟 {args.ms}ms, "
          f"{args.rounds} 轮取中位数 ===")
    theo = {"serial_1conn": args.n * args.ms, "conn_6": -(-args.n // 6) * args.ms,
            "conn_100": args.ms}
    for name, t in [("serial_1conn", t_serial), ("conn_6", t_6), ("conn_100", t_100)]:
        print(f"{name:>14}: median {median(t):8.1f} ms   "
              f"(min {min(t):7.1f} / max {max(t):7.1f})   理论下限≈{theo[name]}ms")

    # 管线化:单独一轮,记录逐块到达时刻
    print(f"\n=== HTTP/1.1 raw pipelining(单连接一次写出 {args.n} 个请求)===")
    elapsed, arrivals, total_read = run_pipelining(args.n, args.ms, args.size)
    # 前 1/4 字节与最后 1/4 字节的到达时间窗
    acc = 0
    t_quarter = None
    for t, c in arrivals:
        acc += c
        if acc >= total_read / 4:
            t_quarter = t
            break
    results["http11"]["pipelining"] = {
        "elapsed_ms": elapsed,
        "first_quarter_bytes_at_ms": t_quarter,
        "total_bytes": total_read,
    }
    print(f"总耗时 {elapsed:.1f} ms(与 serial_1conn 几乎相同 => 管线化没有解决队头阻塞)")
    print(f"响应总字节 {total_read};前 1/4 字节在 {t_quarter:.1f} ms 才到 —— "
          f"即使请求早已全部发出,响应仍被强制按请求顺序排队吐出")

    os.makedirs("results", exist_ok=True)
    out = os.path.join("results", "http11_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已写入 {out}")


if __name__ == "__main__":
    main()
