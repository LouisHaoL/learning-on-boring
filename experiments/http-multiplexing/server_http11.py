"""HTTP/1.1 实验服务器(仅本地实验用)。

基于标准库 ThreadingHTTPServer:每条连接一个 handler 线程,
同一连接上的多个请求仍然是串行处理的(HTTP/1.1 语义决定),
不同连接之间靠线程池并发 —— 这正是浏览器"6 连接"策略的赌注。

端点:
  GET /slow?ms=100&bytes=1024   先睡 ms 毫秒,再返回 bytes 字节
  GET /ping                     健康检查

启动:python server_http11.py --port 8441
"""
import argparse
import socketserver
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/slow":
            ms = int(q.get("ms", ["100"])[0])
            size = int(q.get("bytes", ["1024"])[0])
            time.sleep(ms / 1000.0)
            body = b"x" * size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/ping":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_error(404)

    def log_message(self, *args):  # 静音访问日志,避免干扰计时输出
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8441)
    args = ap.parse_args()
    # request_queue_size 调大,避免 100 并发连接实验时监听队列溢出
    ThreadingHTTPServer.request_queue_size = 256
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"HTTP/1.1 server on http://127.0.0.1:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
