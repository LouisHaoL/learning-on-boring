"""HTTP/2 实验服务器:hypercorn + ASGI,TLS(ALPN 协商 h2 / http/1.1)。

与 server_http11.py 提供完全相同的端点,保证两边实验可对照:
  GET /slow?ms=100&bytes=1024
  GET /ping

同一端口同时支持 h2 和 h1.1(ALPN 协商),方便直接对比。

启动:python server_http2.py --port 8442
依赖:pip install hypercorn
证书:certs/cert.pem + certs/key.pem(自签 localhost,仅供本地实验)
"""
import argparse
import asyncio

import hypercorn.asyncio
from hypercorn.config import Config


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    path = scope["path"]
    query = dict(
        kv.split("=", 1)
        for kv in scope["query_string"].decode().split("&")
        if "=" in kv
    )
    if path == "/slow":
        ms = int(query.get("ms", "100"))
        size = int(query.get("bytes", "1024"))
        await asyncio.sleep(ms / 1000.0)
        body = b"x" * size
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/octet-stream"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
    elif path == "/ping":
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", b"2")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})
    else:
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [(b"content-length", b"0")],
            }
        )
        await send({"type": "http.response.body", "body": b""})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8442)
    args = ap.parse_args()

    import os

    here = os.path.dirname(os.path.abspath(__file__))
    cfg = Config()
    cfg.bind = [f"127.0.0.1:{args.port}"]
    cfg.certfile = os.path.join(here, "certs", "cert.pem")
    cfg.keyfile = os.path.join(here, "certs", "key.pem")
    # ALPN 默认即 [%h2, %http/1.1];同一端口可被两种协议访问
    print(f"HTTP/2 server on https://127.0.0.1:{args.port}", flush=True)
    asyncio.run(hypercorn.asyncio.serve(app, cfg))


if __name__ == "__main__":
    main()
