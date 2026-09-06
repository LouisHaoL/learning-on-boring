// 实验 1:GOMAXPROCS 变化对 CPU 密集并发吞吐的影响。
//
// 运行: go run ./01_gomaxprocs
// 输出: 每个 GOMAXPROCS 取值下的总迭代次数/秒,可整理成数据表。
//
// 预期:吞吐在 GOMAXPROCS <= 物理核数时近似线性上升;超过核数后不再涨甚至
// 回落(sysmon 10ms 抢占 + 缓存抖动)。workers 固定,只动 P 的数量。
package main

import (
	"fmt"
	"runtime"
	"sync"
	"sync/atomic"
	"time"
)

const (
	workers = 8   // 并发 goroutine 数,固定
	chunkMs = 700 // 每档 GOMAXPROCS 的测量时长
)

var stop atomic.Bool

func burn(count *atomic.Int64) {
	var i int64
	for !stop.Load() {
		for j := 0; j < 10000; j++ { // 内层无原子操作,保证纯计算
			i += j
		}
	}
	count.Add(i)
}

var first int64

func measure(procs int) int64 {
	runtime.GOMAXPROCS(procs) // procresize:重建/调整 allp,测量前留出稳定时间
	time.Sleep(100 * time.Millisecond)
	stop.Store(false)
	var total atomic.Int64
	var wg sync.WaitGroup
	start := time.Now()
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() { defer wg.Done(); burn(&total) }()
	}
	time.Sleep(chunkMs * time.Millisecond)
	elapsed := time.Since(start)
	stop.Store(true)
	wg.Wait()
	return int64(float64(total.Load()) / elapsed.Seconds())
}

func main() {
	fmt.Printf("workers=%d 采样=%dms hostCPUs=%d\n\n", workers, chunkMs, runtime.NumCPU())
	fmt.Println("GOMAXPROCS | iters/sec | 相对 P=1")
	fmt.Println("-----------+-----------+---------")
	for _, p := range []int{1, 2, 4, 8, 16, 32} {
		if p > runtime.NumCPU()*4 {
			break
		}
		r := measure(p)
		if p == 1 {
			first = r
		}
		fmt.Printf("%10d | %9d | %s\n", p, r, ratio(r))
	}
}

func ratio(r int64) string {
	return fmt.Sprintf("%.2fx", float64(r)/float64(first))
}
