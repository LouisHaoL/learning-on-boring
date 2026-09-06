# 实验:HTTP/1.1 vs HTTP/2 多路复用与队头阻塞

所有数据均来自本机真实运行(2026-09-06,Windows 10,localhost 回环,无真实网络 RTT)。
配套主文档:`docs/http-multiplexing.md`(相对于 `D:\workspace\learning`)。

## 实验环境

| 项 | 值 |
|---|---|
| OS | Windows 10 Pro for Workstations 10.0.19045 |
| Python | 3.14.4 |
| curl | 8.18.0(mingw32,**未编入 nghttp2**,无 HTTP/2 支持) |
| HTTP/1.1 服务器 | Python 标准库 `ThreadingHTTPServer`(`server_http11.py`,端口 8441) |
| HTTP/2 服务器 | `hypercorn` ASGI + TLS ALPN h2(`server_http2.py`,端口 8442,同一端口兼容 h1.1) |
| HTTP/2 客户端 | `httpx[http2]`(h2 内核)+ 裸 `h2` 库(逐帧观察) |
| 证书 | `openssl req -x509` 自签 localhost(见下方生成命令) |

```bash
# 证书生成(一次性;Git Bash 下需禁用路径转换)
MSYS2_ARG_CONV_EXCL="*" MSYS_NO_PATHCONV=1 \
openssl req -x509 -newkey rsa:2048 -keyout certs/key.pem -out certs/cert.pem \
  -days 30 -nodes -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# 复跑全部实验
bash run_all.sh
```

**环境限制(如实记录):**
- 本机 curl 无 nghttp2,`curl --http2` 不可用。帧级观察改用 Python `h2` 库直连(见实验三),
  能比 `--trace-ascii` 更精确地给出帧类型/stream id/时间戳。
- 客户端并发模型用 asyncio 而非多线程:多线程共享一条 TLS 连接跑 httpcore 的 h2 路径
  在 Windows 上触发 `WinError 10035`(WSAEWOULDBLOCK),且 asyncio 也更贴近真实
  HTTP/2 客户端的事件驱动模型。
- 外网连通性探测:`https://nghttp2.org/httpbin/get` 经 `httpx.Client(http2=True)`
  返回 `HTTP/2 200`,说明外部 h2 可达;但为排除公网 RTT/抖动干扰,计时实验全部在 localhost 完成。

---

## 实验一:HTTP/1.1 三种取数策略 + 管线化

**命令**

```bash
python server_http11.py --port 8441 &
python -X utf8 exp_http11_strategies.py --port 8441
```

参数:N=24 个资源,每个服务端固定延迟 50ms,响应体 2048B,跑 5 轮取中位数。
`conn_6` 的建模是"6 条**持久**连接、每条内部串行消费请求队列"(即浏览器语义)。

**真实输出**(results/exp1_http11_console.txt)

```
=== HTTP/1.1 策略对比  N=24 资源, 每个延迟 50ms, 5 轮取中位数 ===
  serial_1conn: median   1235.5 ms   (min  1219.8 / max  1240.0)   理论下限≈1200ms
        conn_6: median    216.9 ms   (min   206.3 / max   227.5)   理论下限≈200ms
      conn_100: median     57.5 ms   (min    57.3 / max   59.9)   理论下限≈50ms

=== HTTP/1.1 raw pipelining(单连接一次写出 24 个请求)===
总耗时 1164.1 ms(与 serial_1conn 几乎相同 => 管线化没有解决队头阻塞)
响应总字节 50646;前 1/4 字节在 303.3 ms 才到 —— 即使请求早已全部发出,响应仍被强制按请求顺序排队吐出
```

**解读**
- `serial_1conn` ≈ 24×50ms:单条 keep-alive 连接上请求被强制串行,总时间线性叠加。
- `conn_6` ≈ ceil(24/6)×50=200ms:6 条连接把串行批次从 24 压到 4 —— 这就是浏览器
  "每 host 6 连接"限速策略的性能来源与代价。
- `conn_100` 逼近 50ms,但代价是 100 次握手/线程,服务端资源翻倍。
- **管线化失败原因(实测)**:24 个请求在 t=0 一次性发出,但响应必须按请求顺序返回,
  响应 1 未完成前响应 2 的字节一个都不能发。前 1/4 字节直到 ~303ms 才到达(≈6×50ms,
  即前 6 个响应串行完成后),总耗时与纯串行几乎相同。此外实测中若某个响应慢,
  整条队列都被卡住(队头阻塞);浏览器后来还遇到中间代理不兼容问题,最终禁用管线化。

---

## 实验一(补充):连接数扩展曲线

**命令**

```bash
python -X utf8 exp_conn_scaling.py --port 8441
```

同一资源集(24 × 50ms),连接池从 1 扫到 24:

**真实输出**(results/exp4_scaling_console.txt)

```
=== HTTP/1.1 连接数扩展曲线  N=24 资源, 每个 50ms, 5 轮中位数 ===
   连接数       中位耗时ms      相对单连接  边际收益(相对上一档)
     1       1222.3      1.00x        1.00x
     2        625.3      1.95x        1.95x
     3        410.7      2.98x        1.52x
     4        324.7      3.76x        1.26x
     6        217.9      5.61x        1.49x
     8        155.7      7.85x        1.40x
    12        123.6      9.89x        1.26x
    24         57.8     21.15x        2.14x
```

**解读**:加速比 ≈ 资源数/连接数,线性递减(总工作量固定,分给 k 条连接就
除以 k)。收益本身没有明显的"6 拐点"——拐点来自**成本侧**:每条连接都有
握手、内存、服务端线程成本,且同 host 连接数会挤占对其他 host 的预算;
6 是性能与成本的经验折中【实测给出性能面,成本侧为文档知识】。
注意加速比 21.15x 超过 24/24=1 的"批次理论值"仅因并发度对齐了资源数,
此行代表"连接数不再是瓶颈"的上界场景。

---

## 实验二:HTTP/2 单连接多路复用 vs HTTP/1.1

**命令**

```bash
python server_http2.py --port 8442 &
python -X utf8 exp_http2_vs_http11.py --port 8442
```

同一参数集(N=24 / 50ms / 2048B / 5 轮),客户端只改变"协议 + 连接数上限"两个变量。
服务器同一端口经 TLS ALPN 同时支持 h2 与 h1.1,排除服务端差异。

**真实输出**(results/exp2_http2_console.txt)

```
=== HTTP/2 vs HTTP/1.1  N=24 资源, 每个延迟 50ms, 5 轮取中位数 ===
  h2_1conn_multiplexed: median     73.7 ms   (min    64.2 / max    74.3)   [HTTP/2]
        h1_single_conn: median   1480.8 ms   (min  1478.1 / max  1494.5)   [HTTP/1.1]
          h1_six_conns: median    259.0 ms   (min  255.0 / max  259.7)   [HTTP/1.1]
           h1_24_conns: median    103.0 ms   (min  101.2 / max  103.9)   [HTTP/1.1]
```

**解读**
- h2 用 **1 条连接**让 24 个请求各自走独立 stream,总耗时 ≈ 最慢单请求(50ms)+ 帧调度/握手余量。
- h1.1 需要开满 **24 条连接**才接近同样的总耗时,且连接建立成本、服务端内存都更高。
- 相对 h1 六连接浏览器策略,h2 单连接快约 3.5 倍(259ms → 74ms)。
- 注:h1 场景(1480/259/103ms)跑在 hypercorn 上,绝对值比实验一(1235/217/57ms)
  略高,因为 ASGI asyncio 调度开销与 `http.server` 不同;两组实验内部各自自洽,
  不应跨实验直接比较绝对值。

---

## 实验三:帧级观察 —— 响应乱序完成与 DATA 交错

**命令**

```bash
python -X utf8 exp_http2_frames.py --port 8442 --streams 6 --ms 150
```

6 个请求延迟交错设为 150/100/50ms 循环,stream id 1,3,5,7,9,11(奇数=客户端发起)。

**真实输出**(results/exp3_frames_console.txt,节选)

```
TLS ALPN 协商结果: h2
   t(ms)  帧              stream  详情
     0.2  SETTINGS            0  对端设置
    58.5  HEADERS(+END_HEADERS)      5  响应头到达
    58.8  HEADERS(+END_HEADERS)     11  响应头到达
    59.2  DATA                5  512B (累计 512B)
    59.3  END_STREAM          5  该 stream 完成
    59.4  DATA               11  512B ...
   104.0  HEADERS(+END_HEADERS)      3  响应头到达
   104.0  HEADERS(+END_HEADERS)      9  响应头到达
   104.3  DATA                3  512B ...
   104.4  END_STREAM         9  ...
   165.1  HEADERS(+END_HEADERS)      1  响应头到达
   165.3  END_STREAM          7  该 stream 完成

交错证据:12 个 DATA 帧中有 5 次 stream id 切换(HTTP/1.1 下同一连接的响应永远是 1,1,...,2,2,...,切换次数=0)
DATA 帧来自 6 个不同 stream。
```

**解读**
- 完成顺序是 5/11(50ms)→ 3/9(100ms)→ 1/7(150ms):**先发先完成在 h2 上不成立**,
  stream 互不阻塞;HTTP/1.1 下同一连接上请求 1(150ms)不完成,请求 2 一个字节都收不到
  (curl trace 佐证见下)。
- 单条连接上 DATA 帧的 stream id 反复切换,即"多路复用"在帧层面的直接体现。

---

## 附:curl trace 观察 HTTP/1.1 的串行等待

curl 无 http2,只能看 h1.1(两条 300ms 慢请求,`--trace-time` 毫秒时间戳):

```
17:14:43.459000 => Send header, 98 bytes      # 请求 1 发出
17:14:43.761000 <= Recv data, 64 bytes        # 响应 1 完成(302ms 后)
17:14:43.761000 => Send header, 98 bytes      # 请求 2 此刻才发出!
17:14:44.062000 <= Recv data, 64 bytes        # 响应 2 完成(又 301ms)
```

请求 2 的发送时刻 = 响应 1 的完成时刻:同连接上第二个请求根本没提前发出去,
总耗时 603ms ≈ 2×300ms,串行实锤。

---

## 结果文件清单

```
results/http11_results.json      实验一原始数据
results/conn_scaling.json        实验一补充(连接数扫描)原始数据
results/http2_vs_http11.json     实验二原始数据
results/http2_frames.json        实验三帧时间线
results/exp{1,2,3,4}_*_console.txt 实验控制台输出原样留档
```
