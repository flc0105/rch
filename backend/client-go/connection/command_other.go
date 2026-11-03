//go:build !windows

package connection

import "os/exec"

func hideCommandWindow(_ *exec.Cmd) {}
