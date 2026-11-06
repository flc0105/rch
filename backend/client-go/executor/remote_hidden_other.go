//go:build !windows

package executor

import (
	"os"
	"strings"
)

func isHiddenRemoteFile(name string, _ os.FileInfo) bool {
	return strings.HasPrefix(name, ".")
}
