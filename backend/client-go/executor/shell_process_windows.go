//go:build windows

package executor

import (
	"os/exec"
	"strconv"
	"syscall"
)

// Windows shells may spawn child processes; stop the tree, not only cmd.exe.
func configureShellCancellation(cmd *exec.Cmd) {
	cmd.Cancel = func() error {
		if cmd.Process == nil {
			return nil
		}
		stop := exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(cmd.Process.Pid))
		stop.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
		if err := stop.Run(); err != nil {
			return cmd.Process.Kill()
		}
		return nil
	}
}
