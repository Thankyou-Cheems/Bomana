//go:build windows

package main

import (
	"fmt"
	"os/user"
	"syscall"
	"unsafe"
)

// The kernel closes this handle even after a crash. No PID file or stale-lock cleanup.
func claimBridgeInstance() (release func(), acquired bool, err error) {
	current, err := user.Current()
	if err != nil {
		return nil, false, err
	}
	return claimNamedInstance(`Local\BomanaBridge-` + current.Uid)
}

func claimNamedInstance(name string) (release func(), acquired bool, err error) {
	wide, err := syscall.UTF16PtrFromString(name)
	if err != nil {
		return nil, false, err
	}
	handle, _, callErr := kernel32.NewProc("CreateMutexW").Call(0, 0, uintptr(unsafe.Pointer(wide)))
	if handle == 0 {
		return nil, false, fmt.Errorf("Bridge instance mutex: %w", callErr)
	}
	if callErr == syscall.ERROR_ALREADY_EXISTS {
		_ = syscall.CloseHandle(syscall.Handle(handle))
		return nil, false, nil
	}
	return func() { _ = syscall.CloseHandle(syscall.Handle(handle)) }, true, nil
}
