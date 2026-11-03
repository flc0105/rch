//go:build !windows

package executor

import (
	"os/exec"
	"syscall"
)

// Keep a shell and its descendants in one process group so cancellation
// does not leave a child holding stdout/stderr pipes open.
func configureShellCancellation(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
}
