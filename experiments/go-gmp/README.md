# go-gmp 实验集

> **状态:未运行**。本机(Windows)未安装 Go,以下脚本仅完成编写与自审,
> 未产出真实数据;`docs/go-gmp-scheduler.md` 中的论断以 go1.24.0 源码行号
> (本地缓存于 `refs/`)支撑。装 Go ≥1.21 后按本 README 逐个复跑,把输出
> 贴回文档对应小节即可。

## 目录

| 子目录 | 验证什么 | 运行方式 |
|---|---|---|
| `01_gomaxprocs/` | GOMAXPROCS 对 CPU 密集吞吐的影响(数据表) | `go run ./01_gomaxprocs` |
| `02_schedtrace/` | GODEBUG=schedtrace 三种负载形态(A 计算密集 / B 短命 G 风暴 / C 全休眠) | `GODEBUG=schedtrace=100 go run ./02_schedtrace` |
| `03_syscall_handoff/` | 阻塞 syscall 时 P 被抢走交给新 M(retake/handoffp) | `GOMAXPROCS=1 GODEBUG=schedtrace=100 go run ./03_syscall_handoff` |
| `04_stack_size/` | goroutine 初始栈 ≈2KB(stackMin=2048) | `go run ./04_stack_size` |

## 每个实验的观察点

### 01
- P 数 ≤ 物理核数:吞吐近线性;P 数 > 核数:平台期或回落。
- 记录成 `GOMAXPROCS | iters/sec | 相对倍数` 表,贴进文档 §7。

### 02
- 阶段 A:忙碌 P 的 `schedtick` 每屏 +几十,`runqsize` 有存量。
- 阶段 B:`runnext` 频繁非 0(短命 G 走 runnext 插队),全局 `runqueue` 偶有堆积。
- 阶段 C:`idleprocs=gomaxprocs`,`threads=` 稳定不涨。
- 预期 trace 形态见文档 §10(字段语义来自 `schedtrace()` 源码 proc.go:6379)。

### 03
- 关键证据行:`P0: status=2`(P 的 _Psyscall)出现后,`busy` 的输出仍持续推进,
  且 `threads=` 计数 +1 —— 单 P 情况下 sysmon retake(proc.go:6247)把 P0 从
  syscall 手里 CAS 走并 handoffp(proc.go:3030)给新 M。
- 对照:把 `blockSleep(2)` 换成 `time.Sleep(2 * time.Second)` 重跑,status 不变 2、
  threads 不涨 —— time.Sleep 走 gopark(time.go:336),不阻塞线程。

### 04
- `per goroutine` 落在 2~4KB 即验证 `stackMin = 2048`(stack.go:75)+
  `malg(stackMin)`(proc.go:5044)。高于 2048 的部分是阻塞点函数帧与测量窗口扰动。

## refs/(源码缓存,基线 go1.24.0)

| 文件 | 用途 |
|---|---|
| `runtime2.go` | g/m/p/schedt 结构体、G 状态机常量 |
| `proc.go` | 调度主逻辑(schedule/findRunnable/sysmon/retake/队列/抢占) |
| `chan.go` / `time.go` | channel 与 sleep 的调度时机 |
| `stack.go` | 栈初始大小 stackMin |
| `signal_unix.go` | SIGURG 信号抢占 |
| `extern.go` | GOMAXPROCS / GODEBUG 文档 |
| `runtime1.go` | GODEBUG 解析 |

注意:schedtrace 里 P 的 `status=` 数值是 **P** 的状态枚举
(_Pidle=0/_Prunning=1/_Psyscall=2/_Pdead=3,runtime2.go P 结构体附近),
不要和 G 的 `_Grunnable=1...` 混淆。
