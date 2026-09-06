// 实验 3:阻塞 syscall 时 P 与 M 解绑(retake/handoffp)的演示。
//
// 运行: GOMAXPROCS=1 GODEBUG=schedtrace=100 go run ./03_syscall_handoff
//
// 设计:GOMAXPROCS=1(只有 P0)。两个 G:
//   - busy: 纯计算循环(不让出)
//   - sleeper: 陷入真 syscall 阻塞 2 秒(不是 time.Sleep!time.Sleep 走
//     gopark,不占线程;真 syscall 才会把 M 带进内核,G 变 _Gsyscall、P 变 _Psyscall)
// 观察点(schedtrace):
//   1. sleeper 进入 syscall 后出现 `P0: status=2`(P 的 _Psyscall);
//   2. busy 仍能推进 → 说明 sysmon retake 把 P0 从 syscall 手里抢走交给了
//      另一个 M(handoffp),`threads=` 计数随之 +1;
//   3. sleeper 醒来后可能不再绑回原 M(exitsyscallfast_pidle 重取 P)。
// 对照:把 blockSleep 换成 time.Sleep(2s),则 status 不会变 2,threads 不涨
// ——因为 time.Sleep 只挂起 G,不阻塞线程。
package main

import (
	"fmt"
	"runtime"
	"sync"
	"time"
)

func main() {
	fmt.Printf("GOMAXPROCS=%d NumCPU=%d t0=%s\n",
		runtime.GOMAXPROCS(0), runtime.NumCPU(), time.Now().Format("15:04:05.000"))

	var wg sync.WaitGroup

	// G1: 真 syscall,阻塞 M 整整 2 秒(远超 sysmon 的 retake 阈值 ≥20µs)
	wg.Add(1)
	go func() {
		defer wg.Done()
		fmt.Println("sleeper: entering blocking syscall (2s)")
		blockSleep(2)
		fmt.Println("sleeper: syscall returned")
	}()

	// G2: CPU 密集;它能推进本身就说明 P0 被从 syscall 里抢走了
	wg.Add(1)
	go func() {
		defer wg.Done()
		deadline := time.Now().Add(3 * time.Second)
		blocks := 0
		for time.Now().Before(deadline) {
			x := 0
			for i := 0; i < 5e7; i++ { // ~百 ms 量级计算块
				x += i
			}
			_ = x
			blocks++
		}
		fmt.Printf("busy: finished %d compute blocks in 3s\n", blocks)
	}()

	wg.Wait()
	fmt.Println("done; 对照 trace:P0 status=2 与 threads 增长即 handoff 生效")
}
