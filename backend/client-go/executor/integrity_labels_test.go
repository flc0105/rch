package executor

import "testing"

func TestIntegrityRIDMatchesPython(t *testing.T) {
	vectors := map[uint32]string{
		0x0000: "Untrusted", 0x1000: "Low", 0x2000: "Medium",
		0x2100: "Medium High", 0x3000: "High", 0x4000: "System",
		0x5000: "Protected", 0x9999: "Unknown",
	}
	for rid, want := range vectors {
		if got := integrityLabelFromRID(rid); got != want {
			t.Errorf("RID %#x = %q, want %q", rid, got, want)
		}
	}
}
