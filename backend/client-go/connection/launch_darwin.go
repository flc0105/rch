//go:build darwin

package connection

import (
	"context"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

type darwinProc struct {
	pid, ppid, pgid, tpgid int
	tty, name              string
}

func macCommand(name string, args ...string) (string, bool) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, name, args...).Output()
	return string(out), err == nil
}

func readDarwinProc(pid int) (darwinProc, bool) {
	text, ok := macCommand("/bin/ps", "-p", strconv.Itoa(pid), "-o", "ppid=", "-o", "pgid=", "-o", "tpgid=", "-o", "tty=", "-o", "comm=")
	if !ok {
		return darwinProc{}, false
	}
	fields := strings.Fields(text)
	if len(fields) < 5 {
		return darwinProc{}, false
	}
	values := [3]int{}
	for i := range values {
		var err error
		values[i], err = strconv.Atoi(fields[i])
		if err != nil {
			return darwinProc{}, false
		}
	}
	return darwinProc{
		pid: pid, ppid: values[0], pgid: values[1], tpgid: values[2],
		tty: fields[3], name: strings.Join(fields[4:], " "),
	}, true
}

func darwinInteractiveTTY() bool {
	for _, fd := range []uintptr{0, 1, 2} {
		var term syscall.Termios
		_, _, errno := syscall.Syscall(syscall.SYS_IOCTL, fd, uintptr(syscall.TIOCGETA), uintptr(unsafe.Pointer(&term)))
		if errno == 0 {
			return true
		}
	}
	return false
}

func verifiedLaunchdJob(pid int) launchContext {
	listing, ok := macCommand("/bin/launchctl", "list")
	if !ok {
		return launchContext{}
	}
	for _, line := range strings.Split(listing, "\n") {
		fields := strings.Fields(line)
		if len(fields) != 3 || fields[0] != strconv.Itoa(pid) {
			continue
		}
		label := fields[2]
		if strings.Contains(strings.ToLower(label), "anonymous") || strings.Contains(label, "/") {
			continue
		}
		for _, choice := range []struct {
			domain, kind string
			context      launchContext
		}{
			{fmtUIDDomain("gui"), "LaunchAgent", launchContext{"user_service", "launchagent"}},
			{fmtUIDDomain("user"), "LaunchAgent", launchContext{"user_service", "launchagent"}},
			{"system", "LaunchDaemon", launchContext{"system_service", "launchdaemon"}},
		} {
			output, ok := macCommand("/bin/launchctl", "print", choice.domain+"/"+label)
			if !ok {
				continue
			}
			matches := func(key, value string) bool {
				return regexp.MustCompile(`(?im)^\s*` + key + `\s*=\s*` + regexp.QuoteMeta(value) + `\s*$`).MatchString(output)
			}
			if matches("pid", strconv.Itoa(pid)) && matches("state", "running") && matches("type", choice.kind) {
				return choice.context
			}
		}
	}
	return launchContext{}
}

func fmtUIDDomain(prefix string) string { return prefix + "/" + strconv.Itoa(os.Getuid()) }

func detectLaunchContext() launchContext {
	self, ok := readDarwinProc(os.Getpid())
	if !ok {
		return launchContext{"unknown", ""}
	}
	pid := self.ppid
	parents := make([]darwinProc, 0, 8)
	seen := map[int]bool{self.pid: true}
	for pid > 0 && len(parents) < 32 && !seen[pid] {
		seen[pid] = true
		proc, ok := readDarwinProc(pid)
		if !ok {
			break
		}
		parents = append(parents, proc)
		pid = proc.ppid
	}
	ancestry := make([]string, 0, len(parents)*2)
	for _, parent := range parents {
		ancestry = append(ancestry, parent.name)
		if text, ok := macCommand("/bin/ps", "-p", strconv.Itoa(parent.pid), "-o", "command="); ok {
			ancestry = append(ancestry, text)
		}
	}
	managed := launchContext{}
	if cronAncestor(ancestry) {
		managed = launchContext{"scheduled", "cron"}
	} else {
		managed = verifiedLaunchdJob(self.pid)
	}
	direct := ""
	if len(parents) > 0 {
		direct = parents[0].name
	}
	interactive := darwinInteractiveTTY()
	// macOS ps "sess" can report 0; query the process session ID directly.
	sid, sidErr := syscall.Getsid(0)
	return classifyLaunch(launchFacts{
		platform: "darwin", managed: managed, directParent: direct, ancestors: ancestry,
		interactive: interactive, background: self.tpgid > 0 && self.tpgid != self.pgid,
		newSession: sidErr == nil && sid == self.pid, noTerminal: self.tty == "??" || self.tty == "?" || self.tty == "-",
	})
}
