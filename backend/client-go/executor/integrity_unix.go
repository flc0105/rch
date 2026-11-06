//go:build !windows

package executor

import "os"

func detectIntegrity() string {
	if os.Geteuid() == 0 {
		if os.Getenv("SUDO_USER") != "" {
			return "Root (via sudo)"
		}
		return "Root"
	}
	return "User"
}
