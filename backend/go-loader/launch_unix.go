//go:build !windows

package main

import (
	"os"
	"os/exec"
	"syscall"
)

func startDetached(cmd *exec.Cmd, cwd string) (*os.Process, error) {
	cmd.Dir = cwd
	cmd.Stdin = nil
	cmd.Stdout = nil
	cmd.Stderr = nil
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	return cmd.Process, nil
}
func windowsEmbedSupported() error { return nil }
