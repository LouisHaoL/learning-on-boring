// 实验 2:用 GODEBUG=schedtrace 观察调度器。
//
// 运行: GODEBUG=schedtrace=100 go run ./02_schedtrace
//
// 程序依次制造三种负载阶段,每阶段约 1s,便于在 trace 中看到不同形态:
//   阶段A: 4 个 CPU 密集 G —— 应看到忙碌 P 的 schedtick 持续增长、runqsize>0
//   阶段B: 短命 G 风暴     —— 应看到 runnext 频繁非零、本地/全局队列有存量
//   阶段C: 全体休眠        —— 应看到 idleprocs=gomaxprocs、无新线程
package main

import (
	"fmt"
	"runtime"
	"sync"
	"time"
)

func phase(name string) {
	fmt.Printf("\n===== %s =====\n", name)
}

func main() {
	fmt.Printf("GOMAXPROCS=%d NumCPU=%d\n", runtime.GOMAXPROCS(0), runtime.NumCPU())

	// ---- 阶段 A:CPU 密集 ----
	phase("A: 4 CPU-bound goroutines, 1s")
	stopA := make(chan struct{})
	var wgA sync.WaitGroup
	for i := 0; i < 4; i++ {
		wgA.Add(1)
		go func() {
			defer wgA.Done()
			x := 0
			for {
				select {
				case <-stopA:
					return
				default:
					x++
				}
			}
		}()
	}
	time.Sleep(time.Second)
	close(stopA)
	wgA.Wait()

	// ---- 阶段 B:短命 G 风暴 ----
	phase("B: spawn storm, 1s (32 G per batch)")
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		var batch sync.WaitGroup
		for i := 0; i < 32; i++ {
			batch.Add(1)
			go func() { batch.Done() }()
		}
		batch.Wait()
	}

	// ---- 阶段 C:全体休眠 ----
	phase("C: everyone sleeps, 1s (expect all P idle)")
	var wgC sync.WaitGroup
	for i := 0; i < 8; i++ {
		wgC.Add(1)
		go func() {
			defer wgC.Done()
			time.Sleep(900 * time.Millisecond)
		}()
	}
	wgC.Wait()

	fmt.Println("\n===== done =====")
	time.Sleep(300 * time.Millisecond) // 留一拍 trace 收尾
}
