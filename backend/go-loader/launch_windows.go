//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
	"unsafe"
)

func startDetached(cmd *exec.Cmd, cwd string) (*os.Process, error) {
	cmd.Dir = cwd
	cmd.Stdin = nil
	cmd.Stdout = nil
	cmd.Stderr = nil
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: 0x00000008 | 0x00000200,
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	return cmd.Process, nil
}

// windowsEmbedSupported checks the real Windows version rather than the
// manifest-dependent GetVersion API. Python 3.13 needs Windows 8.1+.
func windowsEmbedSupported() error {
	type osVersionInfo struct {
		Size, Major, Minor, Build, Platform uint32
		ServicePack                         [128]uint16
	}
	info := osVersionInfo{}
	info.Size = uint32(unsafe.Sizeof(info))
	proc := syscall.NewLazyDLL("ntdll.dll").NewProc("RtlGetVersion")
	rc, _, err := proc.Call(uintptr(unsafe.Pointer(&info)))
	if rc != 0 {
		return fmt.Errorf("Windows version check failed: %v", err)
	}
	if info.Major < 6 || info.Major == 6 && info.Minor < 3 {
		return fmt.Errorf("Python 3.13 Embed requires Windows 8.1 or newer")
	}
	return nil
}
