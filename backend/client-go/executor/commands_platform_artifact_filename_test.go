package executor

import (
	"testing"
	"time"
)

func TestScreenshotFilenameUsesArtifactTimestamp(t *testing.T) {
	got := buildScreenshotFilename(time.Date(2026, 11, 10, 18, 32, 18, 0, time.Local))
	if got != "screenshot_20261110_183218.png" {
		t.Fatalf("unexpected screenshot name: %q", got)
	}
}
