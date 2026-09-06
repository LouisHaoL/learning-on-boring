#!/usr/bin/env bash
# 一键复跑全部实验(Git Bash):
#   bash run_all.sh
# 前置依赖:
#   python 3.x + pip install hypercorn httpx h2
#   certs/ 下有自签证书(生成命令见 README.md)
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8

cleanup() {
  [[ -n "${PID_H1:-}" ]] && kill "$PID_H1" 2>/dev/null || true
  [[ -n "${PID_H2:-}" ]] && kill "$PID_H2" 2>/dev/null || true
}
trap cleanup EXIT

mkdir -p results

echo "### 启动 HTTP/1.1 服务器(8441)"
python server_http11.py --port 8441 > results/srv_h1.log 2>&1 &
PID_H1=$!

echo "### 启动 HTTP/2 服务器(8442)"
python server_http2.py --port 8442 > results/srv_h2.log 2>&1 &
PID_H2=$!

echo "### 等待就绪"
for _ in $(seq 1 30); do
  ok1=$(curl -s http://127.0.0.1:8441/ping || true)
  ok2=$(curl -sk https://127.0.0.1:8442/ping || true)
  [[ "$ok1" == "ok" && "$ok2" == "ok" ]] && break
  sleep 0.5
done

echo; echo "=== 实验 1/3: HTTP/1.1 取数策略 ==="
python -X utf8 exp_http11_strategies.py --port 8441 2>&1 | tee results/exp1_http11_console.txt

echo; echo "=== 实验 2/4: 连接数扩展曲线 ==="
python -X utf8 exp_conn_scaling.py --port 8441 2>&1 | tee results/exp4_scaling_console.txt

echo; echo "=== 实验 3/4: HTTP/2 多路复用 vs HTTP/1.1 ==="
python -X utf8 exp_http2_vs_http11.py --port 8442 2>&1 | tee results/exp2_http2_console.txt

echo; echo "=== 实验 4/4: HTTP/2 帧交错时间线 ==="
python -X utf8 exp_http2_frames.py --port 8442 --streams 6 --ms 150 2>&1 | tee results/exp3_frames_console.txt

echo; echo "全部完成,原始输出在 results/ 下。"
