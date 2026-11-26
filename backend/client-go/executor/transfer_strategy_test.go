package executor

import (
	"testing"

	"client-go/config"
)

func TestFileTransferStrategyModes(t *testing.T) {
	tests := []struct {
		name     string
		mode     string
		expected string
	}{
		{"HTTP default", config.TransferHTTPStreaming, config.TransferHTTPStreaming},
		{"Native TCP", config.TransferTCPStreaming, config.TransferTCPStreaming},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			strategy := transferStrategyForMode(test.mode)
			if strategy == nil || strategy.mode() != test.expected {
				t.Fatalf("incorrect transfer strategy: %v", strategy)
			}
		})
	}
}
