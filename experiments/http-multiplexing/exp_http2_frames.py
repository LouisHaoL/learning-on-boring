"""实验三:直接用 h2 库做 HTTP/2 客户端,逐帧记录接收事件,展示多路复用的帧交错。

与实验二的 httpx 黑盒不同,这里能看见线上的东西:
  - SETTINGS / WINDOW_UPDATE / HEADERS / DATA / (PING) 等帧
  - DATA 帧上标注 stream id:不同 stream 的数据块在同一时间轴上交错到达

对照:HTTP/1.1 单连接上响应严格按序,只有拿到完整响应 1 才会看到响应 2。

用法:先起 server_http2.py,再运行本脚本(需 pip install h2)。
输出:帧时间线(stdout)+ JSON(results/http2_frames.json)
"""
import argparse
import json
import os
import socket
import ssl
import time

import h2.connection
import h2.events

HOST = "127.0.0.1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8442)
    ap.add_argument("--cert", default="certs/cert.pem")
    ap.add_argument("--streams", type=int, default=6)
    ap.add_argument("--ms", type=int, default=150)
    args = ap.parse_args()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["h2"])
    raw = socket.create_connection((HOST, args.port), timeout=30)
    tls = ctx.wrap_socket(raw, server_hostname=HOST)
    negotiated = tls.selected_alpn_protocol()
    assert negotiated == "h2", f"ALPN 协商结果: {negotiated}(期望 h2)"
    print(f"TLS ALPN 协商结果: {negotiated}\n")

    c = h2.connection.H2Connection()
    c.initiate_connection()
    tls.sendall(c.data_to_send())

    stream_ids = []
    for i in range(args.streams):
        sid = c.get_next_available_stream_id()
        stream_ids.append(sid)
        # 交错请求不同的延迟,让交错更易观察:150 / 100 / 50 / 150 / 100 / 50 ...
        ms = args.ms if i % 3 == 0 else (args.ms * 2 // 3 if i % 3 == 1 else args.ms // 3)
        c.send_headers(sid, [
            (":method", "GET"),
            (":path", f"/slow?ms={ms}&bytes=512"),
            (":authority", f"{HOST}:{args.port}"),
            (":scheme", "https"),
        ])
    tls.sendall(c.data_to_send())
    print(f"已在单条连接上发出 {args.streams} 个请求,stream id: {stream_ids}\n")
    print(f"{'t(ms)':>8}  {'帧':<14} {'stream':>6}  详情")
    print("-" * 72)

    timeline = []
    ended = set()
    t0 = time.perf_counter()
    data_bytes_per_stream = {}

    def now_ms():
        return (time.perf_counter() - t0) * 1000

    def note(ev_name, sid, detail, frame_t):
        line = f"{frame_t:8.1f}  {ev_name:<14} {sid:>6}  {detail}"
        print(line)
        timeline.append({"t_ms": round(frame_t, 2), "event": ev_name,
                         "stream": sid, "detail": detail})

    while len(ended) < len(stream_ids):
        data = tls.recv(65536)
        if not data:
            break
        for ev in c.receive_data(data):
            t = now_ms()
            if isinstance(ev, h2.events.SettingsAcknowledged):
                note("SETTINGS_ACK", 0, "设置协商完成", t)
            elif isinstance(ev, h2.events.ResponseReceived):
                note("HEADERS(+END_HEADERS)", ev.stream_id, "响应头到达", t)
            elif isinstance(ev, h2.events.DataReceived):
                data_bytes_per_stream[ev.stream_id] = \
                    data_bytes_per_stream.get(ev.stream_id, 0) + len(ev.data)
                note("DATA", ev.stream_id,
                     f"{len(ev.data)}B (累计 {data_bytes_per_stream[ev.stream_id]}B)", t)
            elif isinstance(ev, h2.events.StreamEnded):
                note("END_STREAM", ev.stream_id, "该 stream 完成", t)
                ended.add(ev.stream_id)
            elif isinstance(ev, h2.events.WindowUpdated):
                note("WINDOW_UPDATE", ev.stream_id, "流量窗口调整", t)
            elif isinstance(ev, h2.events.PingReceived):
                note("PING", 0, "对端探活", t)
            elif isinstance(ev, h2.events.RemoteSettingsChanged):
                note("SETTINGS", 0, "对端设置", t)
        tls.sendall(c.data_to_send())
    tls.close()

    # 统计交错证据:DATA 事件里 stream id 的切换次数
    data_events = [e for e in timeline if e["event"] == "DATA"]
    switches = sum(
        1 for a, b in zip(data_events, data_events[1:])
        if a["stream"] != b["stream"]
    )
    print(f"\n交错证据:{len(data_events)} 个 DATA 帧中有 {switches} 次 stream id 切换"
          f"(HTTP/1.1 下同一连接的响应永远是 1,1,1,...,2,2,2,...,切换次数=0)")
    inter_streams = len({e["stream"] for e in data_events})
    print(f"DATA 帧来自 {inter_streams} 个不同 stream。")

    os.makedirs("results", exist_ok=True)
    out = os.path.join("results", "http2_frames.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"alpn": negotiated, "stream_ids": stream_ids,
                   "data_frame_switches": switches,
                   "timeline": timeline}, f, ensure_ascii=False, indent=2)
    print(f"结果已写入 {out}")


if __name__ == "__main__":
    main()
