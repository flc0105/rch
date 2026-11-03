package executor

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

var (
	_ = Register(
		"help",
		Usage("help"),
		Help("Show available commands"),
		Group("session"),
		Suggest(),
		cmdHelp,
	)

	_ = Register(
		"kill_instance",
		Usage("kill_instance"),
		Help("Terminate current session"),
		Group("session"),
		Suggest(),
		cmdKillInstance,
	)

	_ = Register(
		"relaunch_instance",
		Usage("relaunch_instance [--no-confirm]"),
		Help("Restart this client in a new process"),
		Group("session"),
		Suggest(),
		cmdRelaunchInstance,
	)

	_ = Register(
		"spawn_instance",
		Usage("spawn_instance"),
		Help("Start another client process"),
		Group("session"),
		Suggest(),
		cmdSpawnInstance,
	)

	_ = Register(
		"cd",
		Usage("cd <path>"),
		Help("Change current working directory"),
		Group("session"),
		Suggest(),
		cmdCd,
	)

	_ = Register(
		"pwd",
		Usage("pwd"),
		Help("Print current working directory"),
		Group("session"),
		Suggest(),
		cmdPwd,
	)
)

func cmdHelp(_ *Session, _ []string) (int, string) {
	return 1, RenderHelpText()
}

func cmdKillInstance(s *Session, args []string) (int, string) {
	if len(args) != 0 {
		return 0, "Usage: kill_instance"
	}
	s.ReportSessionEnd("server_requested_disconnect", "kill_instance")
	_ = s.Sock.Close()
	os.Exit(0)
	return 1, ""
}

func cmdRelaunchInstance(s *Session, args []string) (int, string) {
	if len(args) > 1 || (len(args) == 1 && args[0] != "--no-confirm") {
		return 0, "Usage: relaunch_instance [--no-confirm]"
	}
	if _, err := spawnClientInstance(); err != nil {
		return 0, fmt.Sprintf("Failed to restart client: %v", err)
	}
	s.ReportSessionEnd("client_restart", "relaunch_instance")
	_ = s.Sock.Close()
	os.Exit(0)
	return 1, ""
}

func cmdSpawnInstance(_ *Session, args []string) (int, string) {
	if len(args) != 0 {
		return 0, "Usage: spawn_instance"
	}
	pid, err := spawnClientInstance()
	if err != nil {
		return 0, fmt.Sprintf("Failed to spawn client: %v", err)
	}
	return 1, fmt.Sprintf("New client instance started, pid=%d", pid)
}

func cmdCd(s *Session, args []string) (int, string) {
	if len(args) == 0 {
		return 0, "Usage: cd <path>"
	}

	target := strings.TrimSpace(strings.Join(args, " "))
	if target == "" {
		return 0, "Usage: cd <path>"
	}

	if target == "~" {
		home, err := os.UserHomeDir()
		if err == nil && home != "" {
			target = home
		}
	}

	if !filepath.IsAbs(target) {
		target = filepath.Join(s.Cwd, target)
	}
	target = filepath.Clean(target)

	info, err := os.Stat(target)
	if err != nil {
		return 0, fmt.Sprintf("Failed to change directory: %v", err)
	}
	if !info.IsDir() {
		return 0, fmt.Sprintf("Failed to change directory: not a directory: %s", target)
	}

	s.Cwd = target
	return 1, ""
}

func cmdPwd(s *Session, _ []string) (int, string) {
	return 1, s.Cwd
}
