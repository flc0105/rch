package executor

import (
	"os"
	"os/exec"
	"path/filepath"
)

// Spawn a second copy of this binary without inheriting the current connection.
func spawnClientInstance() (int, error) {
	exe, err := os.Executable()
	if err != nil {
		return 0, err
	}
	cmd := newClientInstanceCommand(exe, os.Args[1:])
	if err := cmd.Start(); err != nil {
		return 0, err
	}
	pid := cmd.Process.Pid
	// Reap the detached child when it eventually exits; it remains independent.
	go func() { _ = cmd.Wait() }()
	return pid, nil
}

func newClientInstanceCommand(exe string, args []string) *exec.Cmd {
	cmd := exec.Command(exe, args...)
	cmd.Dir = filepath.Dir(exe)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = nil, nil, nil
	configureDetachedSpawn(cmd)
	return cmd
}
