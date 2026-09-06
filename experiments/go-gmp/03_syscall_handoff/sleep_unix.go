//go:build unix

package main

import "syscall"

// blockSleep 用真正的内核调用(而非 runtime timer)阻塞当前线程:
// syscall.Nanosleep 会在汇编包装里先 runtime.entersyscall(proc.go:4525),
// G → _Gsyscall、P → _Psyscall,M 陷入内核。
func blockSleep(seconds int) {
	ts := syscall.NsecToTimespec(int64(seconds) * 1e9)
	for {
		if err := syscall.Nanosleep(&ts, &ts); err != syscall.EINTR {
			return
		}
	}
}
