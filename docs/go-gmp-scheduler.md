# Go Runtime GMP 调度器

> **实验受限声明**:本机未安装 Go(未引入重量级环境),本文所有关键论断以
> **源码行号**为支撑,基线为 **golang/go 1.24.0**。runtime 源文件已缓存于
> `experiments/go-gmp/refs/`(runtime2.go / proc.go / chan.go / time.go /
> stack.go / signal_unix.go / extern.go),可离线核对。实验脚本(4 组)已
> 备好但**未实际运行**,存放在 `experiments/go-gmp/`,README 说明复跑方式;
> 本文不包含任何编造的实测数据,schedtrace 输出格式由 `schedtrace()` 源码
> 推导并明确标注。装好 Go 后按实验 README 跑一遍即可把数据补进本文。

源码引用格式:`文件:行号`(均相对 `src/runtime/`)。

## 1. G / M / P 是什么

三张结构体定义在 `runtime2.go`:

- **G**(goroutine,`runtime2.go:396`):一次函数调用的执行上下文。核心字段:
  - `stack`(`:403`):当前栈区间 `[lo, hi)`,初始 `stackMin = 2048` 字节
    (`stack.go:75`),按需增长;
  - `sched gobuf`(`:413`):保存 sp/pc/bp 等寄存器现场,切换时被 `mcall`/`gogo` 恢复;
  - `atomicstatus`(`:430`):状态机(见 §2);
  - `preempt`(`:437`):被标记"该让出了"。
- **M**(machine,`runtime2.go:528`):一个 OS 线程。核心字段:
  - `g0`(`:529`):每线程自带的调度栈上的特殊 G,runtime 代码跑在它上面;
  - `curg`(`:541`):当前正在执行的用户 G;
  - `p`(`m.p`,`muintptr`):back-link,指向当前绑定的 P(空闲时为 0);
  - `lockedg`(`:572`):`runtime.LockOSThread` 建立的 M↔G 固定绑定。
- **P**(processor,`runtime2.go:632`):**逻辑处理器/调度资源**,不是 CPU 也不是线程。
  它是"运行用户代码的许可证",并持有:
  - 本地运行队列 `runq [256]guintptr`(`:654`,无锁环形队列);
  - `runnext`(`:667`):刚被 ready、插队到最前面的 G(见 §4.2);
  - `mcache`、`deferpool`、`sudogcache`、per-P GC 状态——**内存分配与调度解耦的资源缓存**;
  - `schedtick`(`:640`):每轮调度 +1,sysmon 靠它判定"同一 P 跑了多久"。

S(T)ched 全局结构 `schedt`(`runtime2.go:758`):全局运行队列 `runq/runqsize`
(`:793-794`)、空闲 M 链表 `midle/nmidle`、空闲 P 链表 `pidle/npidle`、自旋 M 计数
`nmspinning` 等。

**绑定关系**:G 只能被"持有 P 的 M"执行;`M : P = N : GOMAXPROCS`,M 可远多于 P
(阻塞在 syscall 的 M 不占 P),G 数量理论上无上限。

### 架构图

```
                    schedt (runtime2.go:758)
    ┌───────────────────────────────────────────────────────┐
    │  全局 runq: [gQueue] + runqsize      需持 sched.lock  │
    │  pidle/npidle (空闲P)  midle/nmidle (空闲M)  nmspinning│
    └───────────▲───────────────────────────────▲───────────┘
                │ globrunqget (proc.go:6573)    │ 闲置 M 入睡/唤醒
                │ 1/61 或本地空时来取             │ (stopm/startm/wakep)
   ┌────────────┴──────┐              ┌─────────┴─────────┐
   │  P0 (GOMAXPROCS=1 │              │  P1               │   ... 共 GOMAXPROCS 个 P
   │  ┌──────────────┐ │              │                   │
   │  │ runnext: G7  │ │  stealWork   │  runq:            │
   │  │ runq[256]:   │◄┼───偷一半─────┼─  [G4 G9 G2 ...]  │
   │  │  [G1 G5 ...] │ │ (proc.go:3676│                   │
   │  └──────▲───────┘ │  runqgrab)   └─────────┬─────────┘
   │         │ bind    │                        │ bind
   └─────────┼─────────┘                        │
             │ m.p                              │
   ┌─────────┴───────┐                ┌─────────┴───────┐
   │  M0 (OS thread) │                │  M1 (OS thread) │
   │  g0 调度栈       │                │                 │
   │  curg → G1 执行中│                │  ← syscall 阻塞 │
   └─────────────────┘                └────────┬────────┘
                                               │ 阻塞 >20µs 后 sysmon
                                               │ retake: P 被抢走,
                             新 M 接手此 P      │ M 与 P 解绑继续睡
                             (handoffp:3030)  ◄┘
```

## 2. G 的状态机

状态常量 `runtime2.go:40-107`,转换入口分布在 proc.go/chan.go:

```
                     go 语句 newproc (proc.go:5017)
                              │
                              ▼
                          ┌────────┐  gfget 复用/已消费完毕
                          │ _Gdead │◄──────────────────┐  gfput (proc.go:5178)
                          │  (6)   │                    │
                          └───┬────┘────────────────────┘
                              │ execute() casgstatus
                              ▼
   Gosched() ─────────► ┌────────────┐
   (proc.go:4144        │ _Grunning  │  抢占/系统调用/channel 阻塞
    goschedImpl)        │    (2)     │────────────┬─────────────┬──────────────┐
                        └─────▲──────┘            │             │              │
                              │ schedule()/execute│             │              │
                              ▼                   ▼             ▼              ▼
                       ┌────────────┐      ┌──────────┐  ┌──────────┐  ┌────────────┐
   goready/ready       │ _Grunnable │      │_Gwaiting │  │_Gsyscall │  │_Gpreempted │
   (proc.go:454)──────►│    (1)     │      │   (4)    │  │   (3)    │  │    (9)     │
   放回 runq/runnext   └────────────┘      └──────────┘  └──────────┘  └────────────┘
                            │                  │ channel/sleep/锁   │ exitsyscall     │ GC suspendG
                            │                  │                    │ (proc.go:4663)  │ 异步抢占落地
                            └──────────────────┴────────────────────┴─────────────────┘
                                                        回到 _Grunnable
   另有 _Gcopystack(8)/_Gscan*(栈扫描期间) 等中间态,略。
```

要点:

- `_Grunning` → `_Gwaiting`:主动让出等事件(channel:`chan.go:283` gopark、
  sleep:`time.go:336`、锁等),G 本体从 M 上摘下(dropg),**不占任何线程**;
- `_Grunning` → `_Gsyscall`:G 仍占着 M,但 P 可能被解绑(§5);
- `_Gpreempted`(`runtime2.go:84-89`):GC 发起的异步抢占落地后的中间态,
  "像 _Gwaiting 但没人负责唤醒",由 `satisfyGoroutine` 之类的 resume 流程接管。

## 3. 调度时机(什么时候发生 G 切换)

| 触发点 | 路径 | 源码 |
|---|---|---|
| `go` 关键字 | 编译为 `runtime.newproc` → `newproc1` 建 G → `runqput(next=true)` 放进当前 P 的 `runnext` | `proc.go:5017, 5035` |
| channel 发送/接收阻塞 | `chansend`/`chanrecv` 调 `gopark` 挂起;对端到达时 `goready` | `chan.go:283, 664, 350, 742` |
| `time.Sleep` | `timeSleep` → `gopark` + 挂定时器到当前 P 的 timer 堆 | `time.go:305, 336` |
| 主动让出 `runtime.Gosched()` | `goschedImpl`:G → `_Grunnable` 进全局队列,当前 M 重新 `schedule()` | `proc.go:4144, 6538` |
| 系统调用 | 编译器在 cgo/syscall 包装层插 `entersyscall`/`exitsyscall` | `proc.go:4525, 4663` |
| GC STW / 标记 | stopTheWorld 等待所有 P 停;标记辅助 `gcAssistAlloc` 让出;后台 mark worker 由 `findRunnable` 优先调度 | `proc.go:3308-3313` |
| **抢占**(异步) | sysmon 每 ≥10ms 对长跑 G 所在 P 调 `preemptone` → 向 M 发 `SIGURG` | `proc.go:6245, 6350; signal_unix.go:73, 368` |
| 抢占(协作兜底) | `gp.preempt=true` + `stackguard0=stackPreempt`,下次函数序言的栈溢出检查跳 `morestack` → 让出 | `proc.go:6369-6375` |

### 协作式 → 信号抢占的演进(Go 1.14 分界)

- **1.14 之前**:只有协作式抢占。`preemptone` 把 `stackguard0` 改成哨兵值
  `stackPreempt`,依赖 G 在下一次函数调用时触发 `morestack` 检查发现它。后果:
  **不含函数调用的死循环(如 `for {}`)永远不会让出**,GC 等它 STW 就整个程序卡死,
  这也是当年 "goroutine 泄漏卡死 GC" 一类 issue 的根源。
- **1.14 起**(CL 362120 一代工作):`preemptone` 在设置协作标志之外,追加
  `preemptM(mp)`(`proc.go:6378-6381`)——向目标线程发 **`SIGURG`**
  (`signal_unix.go:73: const sigPreempt = _SIGURG`),信号处理路径
  `sigtrampgo` → `doSigPreempt`(`signal_unix.go:341, 431`)检查栈上是否有
  安全注入点,有则把 `asyncPreempt` 调用**推入目标 PC**,无需目标配合即可打断
  纯计算循环。可用 `GODEBUG=asyncpreemptoff=1` 关闭(`extern.go:220-223`)。
  选 SIGURG 是因为它极少被用户程序占用,且默认行为(无人处理时)是静默忽略。

## 4. 队列、work-stealing 与 1/61

### 4.1 三层找活:`findRunnable`(proc.go:3271)

一个 M 醒来没活干时,`schedule()` → `findRunnable()` 按固定顺序找 G(不空手返回,
阻塞等待):

1. 本地 `runqget`(`:3354`,无锁,继承时间片 `inheritTime`);
2. **1/61 全局队列检查**(`:3302-3309`):
   ```go
   if pp.schedtick%61 == 0 && sched.runqsize > 0 {
       gp := globrunqget(pp, 1)
   ```
   源码注释原文:"Check the global runnable queue once in a while to ensure
   fairness. Otherwise two goroutines can completely occupy the local runqueue
   by constantly respawning each other." 61 是个素数,避免与其他周期性模式共振;
   这保证"两个 G 互相 spawn、把本地队列喂满"的模式下全局队列也偶尔被消费;
3. 非阻塞 `netpoll(0)` 扫一遍就绪的网络 fd(`:3370-3384`,见 §6);
4. **work-stealing**:`stealWork`(`:3676`)。随机起点遍历所有 P,最多 4 轮;
   通过 `runqgrab`(`:6931`)**偷走目标 P 本地队列的一半**;最后一轮才顺带偷
   timer 和对方的 `runnext`(注释:runnext 是 last resort——偷走 runnext 会破坏
   "producer-consumer 局部性",见 `:3689-3691`);
5. 实在没有:`stopm` 把 M 睡进 `midle`(proc.go:2891)。

自旋 M 机制(`:3398-3403`):允许的自旋 M 数 ≤ 忙 P 的一半(`2*nmspinning <
gomaxprocs - npidle` 才进入 stealing),防止 GOMAXPROCS 很大但并行度低时,
一堆 M 空转烧 CPU。持 P 自旋的 M 找到活后 `resetspinning`(`:3869`)并可能
`wakep`(`:3111`)再唤醒一个 M。

### 4.2 runnext:生产者-消费者局部性

`runqput(pp, gp, next=true)`(`proc.go:6742`)不进环形队列,而是 CAS 到
`runnext`(`:6763-6770`);原来的 runnext 被踢进队列尾。效果:`go` 出来的
G 或刚 ready 的对端 G 会**立刻被当前 P 的下一轮调度执行**,省去排队延迟——
"一组互相通信的 G 被当作一个单元调度"(runtime2.go:668-676 注释)。
它的代价由 sysmon 兜底:runnext 与当前 G 共享时间片(`inheritTime`),若互相
喂 G 形成乒乓,`retake` 会在 10ms 后 `preemptone` 打断这一组
(`proc.go:6744-6750` 注释,依赖 `haveSysmon`)。

### 4.3 本地队列满:runqputslow

本地 256 格(`runtime2.go:654`)装不下时,`runqputslow`(`proc.go:6788`)
取**队头一半 + 新 G 共 129 个**批量挂到全局队列(`globrunqputbatch:6563`),
给其他 P 留出偷取空间。`globrunqget`(`:6573`)一次取 `min(runqsize/gomaxprocs+1, max)`,
批量搬运减少全局锁竞争。

## 5. 系统调用:syscall 时 P 与 M 解绑

进入 syscall 前后,M 上的 G 状态切到 `_Gsyscall`;此时 P 分两种命运
(`reentersyscall` proc.go:4436):

- **快速路径**:`entersyscall`(`:4525`)只把 P 标为 `_Psyscall`,**不解绑**——
  大多数 syscall 很快返回,M 出来后原 P 还在(`exitsyscall` → `exitsyscallfast`
  → `exitsyscallfast_reacquired` `:4749, 4788`),零开销拿回。
- **阻塞路径**:若 syscall 长睡,`sysmon` 的 `retake`(`:6247`)发现某 P 在
  `_Psyscall` 超过一个 tick(至少 20µs,`:6283` 注释):
  ```
  if runqempty(pp) && sched.nmspinning+npidle > 0 && pd.syscallwhen+10ms > now
      continue    // 没人要活干且没睡满 10ms:不抢
  atomic.Cas(&pp.status, s, _Pidle); handoffp(pp)   // :6309-6320
  ```
  **P 被 CAS 走并交给别的(或新建的)M**,睡在 syscall 里的 M 与 P 彻底解绑。
  GOMAXPROCS 限制的是"同时执行用户代码的线程数"而不是线程总数——这正是
  `extern.go:230-233` 那段文档的含义("There is no limit to the number of
  threads that can be blocked in system calls")。
- **退出 syscall**:`exitsyscallfast_pidle`(`:4806`)先试拿回原 P(oldp),
  不行就取空闲 P,再不行 `exitsyscall0`(`:4827`)把 G 挂到全局队列、M 睡觉。

**handoff 的意义**:哪怕一个 G 阻塞在 `read()` 上,其他 G 也不受影响——
它的 M 被独占,但 P(调度能力 + mcache)被抽走继续服务别的 G。
这也是 Go 服务在慢 IO 下吞吐不塌的根本原因。

**锁死的 goroutine 与 M handoff**:`LockOSThread` 的 G(lockedm/lockedg,
`runtime2.go:469, 572`)syscall 时 P 不能随便给别人——`handoffp` 里有对称
检查(proc.go:3030 注释:"The conditions here and in handoffp must agree")。
而 `chansend` 到 nil channel 这类永久阻塞,由运行时 `checkdead`(proc.go,
由 nmidle/nmsys 计数触发)在**所有 P 空闲且无 runnable G**时判定死锁抛
"all goroutines are asleep - deadlock!"。注意它检测的是调度器级全休眠,
G 之间互相等的逻辑死锁(还有活 G 在跑)不在此列。

## 6. netpoller 集成

网络 fd 通过非阻塞 IO + 就绪通知(kqueue/epoll/IOCP)注册进 netpoller。
G 在网络读写上"阻塞"时其实只是 `gopark` 成 `_Gwaiting`,**没有线程陷进内核**。
ready G 的三条回流路径:

1. `findRunnable` 里的非阻塞 `netpoll(0)`(`proc.go:3370-3384`);
2. `stealWork` 没偷到活时的**阻塞 `netpoll(delay)`**:M 睡在 poller 上等事件
   或 `netpollBreak`,醒来带一串就绪 G(`injectglist`);
3. sysmon 发现 `lastpoll` 超过 10ms 没人 poll(所有 P 都忙),替它跑一次
   非阻塞 netpoll 并 `injectglist`(proc.go sysmon 段,`:6170-6190` 附近)。

所以 netpoller 不是第 4 种队列,而是 **M 找不到可运行 G 时的"等事件"点**:
调度器把"IO 等待"统一收敛成 `_Gwaiting` + 事件驱动唤醒。

## 7. GOMAXPROCS 的真实含义

`extern.go:230-234` 的官方定义:限制**同时执行用户级 Go 代码的 OS 线程数**。
据此:

- 它 **= P 的个数**(`procresize` 建 allp),不是线程数、不是 goroutine 数;
- 阻塞在 syscall 的线程不占名额(§5),所以 `GOMAXPROCS=4` 的进程可以有几十个线程;
- CPU 密集场景下它约等于可用并行度,默认 = CPU 核数(容器里是配额感知的
  cgroup limit;1.25 起默认值还会随 cgroup 动态调整——本文基线 1.24 为
  启动时一次性确定);
- 运行时调用 `runtime.GOMAXPROCS(n)` 会触发 `stopTheWorldSemi` 式的
  `procresize`:停住所有 P 重排队列、增删 allp,有可观 STW 开销,**不要在
  热路径上频繁改**;
- 对纯 CPU 密集任务,设超过核数通常只增加抢占与缓存抖动;对 syscall 重的
  任务,加大 GOMAXPROCS 常能提高吞吐(因为每个陷进 syscall 的 P 短期不可复用)。

## 8. 为什么 goroutine 切换比线程切换便宜

| 维度 | OS 线程切换 | goroutine 切换 |
|---|---|---|
| 触发方 | 内核(中断/系统调用) | 用户态函数(mcall/gogo,无 syscall) |
| 现场大小 | 全量寄存器 + FPU/浮点状态 + 内核调度上下文 | gobuf 里约 SP/PC/BP/g 几个字(`runtime2.go:298`) |
| 调度决策 | 内核通用调度器(CFS 等),需考虑优先级/cgroup/负载均衡 | `findRunnable` 的固定顺序查表,多为无锁操作 |
| 缓存/TLB | 可能跨核迁移、地址空间切换 | 优先留在同 P:runnext + 本地队列 + per-P mcache 热缓存 |
| 栈 | 固定大(通常 MB 级),切换伴随 cache pollution | 2KB 起步(`stack.go:75`),百万级 G 才耗 GB |
| 唤醒延迟 | 依赖内核 tick/中断 | runnext 立即执行;自旋 M 即刻接活;runq 半偷 |

关键设计:**P 的存在让"切换"大部分时候根本不发生**——G 在同一个 P 上排队,
mcache/timer/deferpool 全是热的;只有 work-stealing 和 syscall handoff 才有
跨 P 成本。

## 9. sysmon:独立于调度器的看门狗

`sysmon`(proc.go:6089)由 `mcount` 之外的独立 M 运行(**没有 P**,
写死绕过调度器),睡 20µs → 指数退避至上限 10ms(`:6097-6104` 一带),
每轮做四件事:

1. `netpoll` 兜底(§6 路径 3);
2. `retake(now)`(`:6247`):从超时 syscall 手里抢 P(`handoffp`);同时对
   `schedtick` 超过 `forcePreemptNS = 10ms`(`:6245`)没换的 P 调
   `preemptone`——**这就是 Go 的"时间片"**:没有显式时间片轮转,只有
   sysmon 的 10ms 抢占上限;
3. 唤醒 scavenger;GC 触发检查:超过 `forcegcperiod = 2 * 60 * 1e9`
   (`proc.go:6075`)未 GC 且 `gcTriggerTime` 满足时,把 forcegc G
   `injectglist` 进调度(`proc.go:6219-6226`);每轮打点 `schedtrace`
   (`proc.go:6228-6231`);

所以 "goroutine 是协作式调度" 在 1.14 之后已不准确(见 §3 演进小节),但
**抢占精度只有 sysmon 唤醒粒度(20µs~10ms)**,实时性不能指望它。

## 10. GODEBUG=schedtrace 输出逐字段解读

> 以下为**格式说明**,由 `schedtrace()` 源码(proc.go:6379-6420 的 print 语句)
> 推导,本机未实测运行;字段语义与 print 参数一一对应。装 Go 后运行
> `experiments/go-gmp/02_schedtrace/` 即可得到真实样例。

每 100ms(`GODEBUG=schedtrace=100`,毫秒数在 `extern.go:390` 处解析进
`debug.schedtrace`)打印一行:

```
SCHED 5000ms: gomaxprocs=8 idleprocs=5 threads=12 spinningthreads=1
              needspinning=0 idlethreads=4 runqueue=2 [detailed 时有第二行]
  P0: status=1 schedtick=42 syscalltick=7 m=3 runqsize=3 runnext=0x...
  P1: status=4 schedtick=1337 syscalltick=1 m=-1 runqsize=0 runnext=0
  ...
```

| 字段 | 含义 | 对应源码变量 |
|---|---|---|
| `5000ms` | 程序启动至今 | `now-starttime`(proc.go:6384) |
| `gomaxprocs` | P 总数 | `gomaxprocs` |
| `idleprocs` | 空闲 P 数,≈ 忙碌逻辑处理器数 = gomaxprocs-idleprocs | `sched.npidle` |
| `threads` | 已创建 OS 线程总数(含 syscall 阻塞中的) | `mcount()`(proc.go:5427) |
| `spinningthreads` | 自旋找活的 M 数 | `sched.nmspinning` |
| `idlethreads` | 睡在 midle 里的 M 数 | `sched.nmidle` |
| `runqueue` | **全局队列**长度 | `sched.runqsize` |
| `P*: status=` | 0=_Pidle 1=_Prunning 2=_Psyscall 3=_Pgcstop 4=_Pdead(`runtime2.go:120-158`;注意这是 **P** 的状态枚举,数值与 G 的不同,别混淆) | `pp.status` |
| `schedtick` | 该 P 累计调度轮数;长期不涨 = 可能在跑同一个 G | `pp.schedtick` |
| `syscalltick` | 该 P 累计 syscall 进出次数 | `pp.syscalltick` |
| `m=` | 绑定的 M id,-1 = 无 | `pp.m` |
| `runqsize` | **该 P 本地队列**长度(0~256) | runqtail-runqhead |
| `runnext` | 插队 G 指针,非 0 说明刚有 G 被让位 | `pp.runnext` |

`GODEBUG=schedtrace=100,scheddetail=1` 会额外打印每个 G 的状态、等待原因、
sudog 等,适合查泄漏;日常观察负载用 `schedtrace=1000` 更可读。

## 11. 常见误解澄清

1. **"goroutine 就是轻量线程"** — 不对,至少错三处:
   - 线程是内核对象,goroutine 是 `runtime2.go:396` 里的纯用户态结构体,
     内核根本不知道它存在;
   - 线程调度由内核驱动,goroutine 的"调度"是 `findRunnable` 查队列 +
     sysmon 抢占,一层完全在用户态;
   - "轻量"不止栈小:G 阻塞在 channel/sleep 上时**不持有任何线程**,
     `_Gwaiting` 状态的 G 只有几百字节结构体+栈;线程阻塞就是线程没了。
   准确说法:**goroutine 是被 M:N 复用到 OS 线程上的可中断执行流,P 是复用的仲裁者**。
2. **"GOMAXPROCS = 最大线程数"** — 错。它只限制执行用户代码的并行 M;
   syscall 里的 M 不计费(`extern.go:230-233`),`threads` 字段可以远大于它。
3. **"goroutine 调度是抢占式的/是协作式的"** — 单说哪个都不准。1.14 前纯协作
   (死循环卡死 GC);1.14 起是 **信号异步抢占 + 协作检查混合**,但"抢占"只在
   函数边界或信号注入点生效,持续 `for {}` 且 `asyncpreemptoff=1` 仍会卡死 STW。
4. **"本地队列满了就丢全局队列"** — 只丢**一半**(129 个,含新 G),
   `runqputslow` proc.go:6788;设计意图是把全局队列当溢出缓冲 + 偷取源,
   而不是常态路径。
5. **"1/61 = 每秒一次查全局队列"** — 错。是 `schedtick%61`,按**调度轮次**计,
   与时间无关;P0 可能一秒 tick 几万次。
6. **"goroutine 阻塞会拖垮整个程序"** — channel/sleep/网络 IO 完全不会
   (gopark 摘 G 不占线程);只有两种会拖:写法糟糕的纯计算死循环(靠 sysmon
   10ms 抢占兜底)和陷在 syscall 里太久(靠 retake 抢 P 兜底)。兜底都有
   20µs~10ms 的迟滞。
7. **"P 就是 CPU 核"** — P 是软件对象,数量可随意改,与核数默认相等只是
   一个合理的默认并行度选择。
8. **"goroutine 切换永远是纳秒级"** — 快路径(同 P runnext/本地队列)确实是
   ~百 ns 量级的两次跳转;但 work-stealing、全局队列锁、syscall handoff、
   GC STW 期间的重排都可能让某次切换贵几个数量级。平均值不代表尾延迟,
   延迟敏感场景应该用 `GODEBUG=schedtrace` + runtime/trace 实测而非套公式。

## 12. 参考与复跑

- 源码(本地缓存,基线 go1.24.0):`experiments/go-gmp/refs/`
  - runtime2.go(g/m/p/schedt 结构体与状态机)
  - proc.go(schedule/findRunnable/sysmon/retake/抢占/队列全部主逻辑)
  - chan.go、time.go(channel 与 sleep 的调度时机)
  - stack.go(栈初始大小)、signal_unix.go(信号抢占)、extern.go(GOMAXPROCS/GODEBUG)
- 在线:https://github.com/golang/go/tree/go1.24.0/src/runtime
  设计文档:runtime/proc.go 头部 "Worker thread parking/unparking" 注释;
  scheddesign 文档 https://golang.org/s/go11sched ;1.14 抢占提案 #24543
  (https://github.com/golang/go/issues/24543)。
- 实验脚本(装 Go ≥1.21 后可跑,README 见 `experiments/go-gmp/`):
  01_gomaxprocs(吞吐对比)、02_schedtrace(trace 解读)、03_syscall_handoff
  (阻塞 syscall 观察 P 被抢)、04_stack_size(2KB 初始栈验证)。
