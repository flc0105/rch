//go:build windows

package executor

import (
	"os"
	"strings"
	"syscall"
)

func isHiddenRemoteFile(name string, info os.FileInfo) bool {
	if strings.HasPrefix(name, ".") {
		return true
	}
	if attributes, ok := info.Sys().(*syscall.Win32FileAttributeData); ok {
		return attributes.FileAttributes&syscall.FILE_ATTRIBUTE_HIDDEN != 0
	}
	return false
}
