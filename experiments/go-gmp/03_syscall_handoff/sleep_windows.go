//go:build windows

package main

import "syscall"

// blockSleep 用 kernel32.Sleep 阻塞当前线程。
// LazyProc.Call 底层走 syscall.SyscallN,其汇编包装会先调用
// runtime.entersyscall(proc.go:4525):G → _Gsyscall、P → _Psyscall,
// M 陷入内核。这与 time.Sleep(纯 runtime timer,走 gopark)完全不同。
var sleepProc = syscall.NewLazyDLL("kernel32.dll").NewProc("Sleep")

func blockSleep(seconds int) {
	sleepProc.Call(uintptr(uint32(seconds) * 1000))
}
