// 实验 4:goroutine 初始栈 2KB 的验证。
//
// 运行: go run ./04_stack_size
//
// 原理:让 N 个 goroutine 阻塞在一个未关闭的 channel 上(栈不增长、
// G 不退出),用 runtime.MemStats 的 StackSys 增量除以 N,得到每 G 栈均摊。
// 源码依据:stack.go:75 `stackMin = 2048`;proc.go:5044 newproc1 中
// `newg = malg(stackMin)`。
//
// 注意:实测值会略高于 2048(同步阻塞点有少量函数帧、g 结构体本身不算栈、
// 测量窗口内仍有个别 G 在调度),2~4KB 量级即算吻合。
package main

import (
	"fmt"
	"runtime"
	"sync"
	"time"
)

const n = 200_000

func main() {
	runtime.GC()
	var before runtime.MemStats
	runtime.ReadMemStats(&before)

	// n 个 G 阻塞在同一个空 channel 的接收上(_Gwaiting,不占任何线程)
	release := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-release
		}()
	}
	time.Sleep(1 * time.Second) // 等它们全部挂起

	runtime.GC()
	var after runtime.MemStats
	runtime.ReadMemStats(&after)

	delta := float64(after.StackSys) - float64(before.StackSys)
	fmt.Printf("goroutines      : %d\n", n)
	fmt.Printf("StackSys before : %d KiB\n", before.StackSys/1024)
	fmt.Printf("StackSys after  : %d KiB\n", after.StackSys/1024)
	fmt.Printf("delta           : %.1f KiB\n", delta/1024)
	fmt.Printf("per goroutine   : %.0f bytes  (期望 ~2048 量级)\n", delta/n)
	fmt.Printf("StackInuse delta: %.1f KiB, per G %.0f bytes\n",
		float64(after.StackInuse-before.StackInuse)/1024,
		float64(after.StackInuse-before.StackInuse)/n)

	close(release)
	wg.Wait()
}

// unsafe 扩展思路(需要 linkname 技巧,此处仅作说明):
// 拿到 *g 后直接读 gp.stack.hi - gp.stack.lo 即该 G 当前栈区间大小,
// 未调深栈的新 G 应精确等于 stackMin(2048)。
