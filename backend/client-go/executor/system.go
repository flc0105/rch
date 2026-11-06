package executor

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

func detectOSVersion() string {
	switch runtime.GOOS {
	case "windows":
		if out, err := exec.Command("cmd", "/C", "ver").CombinedOutput(); err == nil {
			return strings.TrimSpace(string(out))
		}
	case "darwin":
		if out, err := exec.Command("sw_vers", "-productVersion").CombinedOutput(); err == nil {
			return strings.TrimSpace(string(out))
		}
	default:
		if out, err := exec.Command("uname", "-r").CombinedOutput(); err == nil {
			return strings.TrimSpace(string(out))
		}
	}
	return "unknown"
}

func detectMachineToken() string {
	host, _ := os.Hostname()
	return fmt.Sprintf("%s-%d", sanitizeToken(host), time.Now().UnixNano())
}

func sanitizeToken(s string) string {
	s = strings.TrimSpace(strings.ToLower(s))
	if s == "" {
		return "unknown"
	}
	s = strings.ReplaceAll(s, " ", "-")
	return s
}

func currentUserName() string {
	if runtime.GOOS == "windows" {
		return os.Getenv("USERNAME")
	}
	return os.Getenv("USER")
}

func safeExecutablePath() string {
	path, err := os.Executable()
	if err != nil {
		return ""
	}
	return path
}

func listIPv4Addrs() []string {
	result := make([]string, 0)
	seen := make(map[string]struct{})

	ifaces, err := net.Interfaces()
	if err != nil {
		return result
	}

	for _, iface := range ifaces {
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, addr := range addrs {
			ipNet, ok := addr.(*net.IPNet)
			if !ok || ipNet.IP == nil || ipNet.IP.IsLoopback() {
				continue
			}
			ip := ipNet.IP.To4()
			if ip == nil {
				continue
			}
			key := ip.String()
			if _, exists := seen[key]; exists {
				continue
			}
			seen[key] = struct{}{}
			result = append(result, key)
		}
	}

	sort.Strings(result)
	return result
}

func formatDict(values map[string]string) string {
	if len(values) == 0 {
		return ""
	}

	keys := make([]string, 0, len(values))
	maxLen := 0
	for key := range values {
		keys = append(keys, key)
		if len(key) > maxLen {
			maxLen = len(key)
		}
	}
	sort.Strings(keys)

	lines := make([]string, 0, len(keys))
	for _, key := range keys {
		lines = append(lines, fmt.Sprintf("%-*s : %s", maxLen, key, values[key]))
	}
	return strings.Join(lines, "\n")
}

func parsePositiveInt(value string) string {
	n, err := strconv.Atoi(value)
	if err != nil {
		return value
	}
	return strconv.Itoa(n)
}
