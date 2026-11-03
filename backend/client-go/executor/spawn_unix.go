//go:build !windows

package executor

import (
	"os/exec"
	"syscall"
)

func configureDetachedSpawn(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}
