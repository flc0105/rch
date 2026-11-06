//go:build linux

package connection

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

type linuxProc struct {
	pid, ppid, pgrp, session, tty, tpgid int
	name, command                        string
}

var systemdLoginUnit = regexp.MustCompile(`^user@\d+\.service$`)

func readLinuxProc(pid int) (linuxProc, error) {
	data, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return linuxProc{}, err
	}
	end := strings.LastIndexByte(string(data), ')')
	if end < 0 || end+2 >= len(data) {
		return linuxProc{}, fmt.Errorf("invalid /proc stat")
	}
	// The name in parentheses may itself contain spaces or parentheses.
	fields := strings.Fields(string(data[end+2:]))
	if len(fields) < 6 {
		return linuxProc{}, fmt.Errorf("incomplete /proc stat")
	}
	values := [5]int{}
	for i, index := range []int{1, 2, 3, 4, 5} {
		values[i], err = strconv.Atoi(fields[index])
		if err != nil {
			return linuxProc{}, err
		}
	}
	name := string(data[strings.IndexByte(string(data), '(')+1 : end])
	if executable, err := os.Readlink(fmt.Sprintf("/proc/%d/exe", pid)); err == nil {
		name = filepath.Base(executable)
	}
	command, _ := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
	return linuxProc{pid, values[0], values[1], values[2], values[3], values[4], name,
		strings.ReplaceAll(string(command), "\x00", " ")}, nil
}

func linuxAncestorChain(pid int) []linuxProc {
	result := make([]linuxProc, 0, 8)
	seen := map[int]bool{pid: true}
	for len(result) < 32 && pid > 1 {
		proc, err := readLinuxProc(pid)
		if err != nil || proc.ppid <= 0 || seen[proc.ppid] {
			break
		}
		pid = proc.ppid
		seen[pid] = true
		parent, err := readLinuxProc(pid)
		if err != nil {
			break
		}
		result = append(result, parent)
	}
	return result
}

func linuxInteractiveTTY() bool {
	for _, fd := range []uintptr{0, 1, 2} {
		var term syscall.Termios
		_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, fd, uintptr(syscall.TCGETS), uintptr(unsafe.Pointer(&term)))
		if errno == 0 {
			return true
		}
	}
	return false
}

func verifiedSystemdUnit(pid int) launchContext {
	content, err := os.ReadFile(fmt.Sprintf("/proc/%d/cgroup", pid))
	if err != nil {
		return launchContext{}
	}
	for _, line := range strings.Split(string(content), "\n") {
		parts := strings.SplitN(line, ":", 3)
		if len(parts) != 3 || (parts[1] != "" && parts[1] != "name=systemd") {
			continue
		}
		segments := strings.Split(strings.Trim(parts[2], "/"), "/")
		unit := ""
		userUnit := false
		for _, segment := range segments {
			if systemdLoginUnit.MatchString(segment) {
				userUnit = true
			} else if strings.HasSuffix(segment, ".service") {
				unit = segment
			}
		}
		if unit == "" {
			continue
		}
		args := []string{}
		if userUnit {
			args = append(args, "--user")
		}
		args = append(args, "show", unit, "--property=MainPID", "--property=ActiveState")
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		output, err := exec.CommandContext(ctx, "systemctl", args...).Output()
		cancel()
		if err != nil {
			continue
		}
		properties := map[string]string{}
		for _, row := range strings.Split(string(output), "\n") {
			if kv := strings.SplitN(row, "=", 2); len(kv) == 2 {
				properties[kv[0]] = kv[1]
			}
		}
		if properties["MainPID"] == strconv.Itoa(pid) && properties["ActiveState"] == "active" {
			if userUnit {
				return launchContext{"user_service", "systemd_user"}
			}
			return launchContext{"system_service", "systemd"}
		}
	}
	return launchContext{}
}

func detectLaunchContext() launchContext {
	self, err := readLinuxProc(os.Getpid())
	if err != nil {
		return launchContext{"unknown", ""}
	}
	parents := linuxAncestorChain(self.pid)
	ancestry := make([]string, 0, len(parents)*2)
	for _, parent := range parents {
		ancestry = append(ancestry, parent.name, parent.command)
	}
	managed := launchContext{}
	if cronAncestor(ancestry) {
		managed = launchContext{"scheduled", "cron"}
	} else {
		managed = verifiedSystemdUnit(self.pid)
	}
	direct := ""
	if len(parents) > 0 {
		direct = parents[0].name
	}
	interactive := linuxInteractiveTTY()
	return classifyLaunch(launchFacts{
		platform: "linux", managed: managed, directParent: direct, ancestors: ancestry,
		interactive: interactive, background: self.tty != 0 && self.tpgid != self.pgrp,
		newSession: self.session == self.pid, noTerminal: self.tty == 0,
	})
}
