//go:build !windows

package executor

import (
	"os"
	"testing"
)

func TestPosixIntegrityRespectsEffectiveUID(t *testing.T) {
	value := detectIntegrity()
	if os.Geteuid() != 0 && value != "User" {
		t.Errorf("non-root integrity = %q", value)
	}
	if os.Geteuid() == 0 && value != "Root" && value != "Root (via sudo)" {
		t.Errorf("root integrity = %q", value)
	}
}
