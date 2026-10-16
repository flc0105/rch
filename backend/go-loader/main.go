package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"rch-go-loader/config"
)

type BundleBuildResponse struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    struct {
		FileName     string `json:"file_name"`
		DownloadURL  string `json:"download_url"`
		BuildVersion string `json:"build_version"`
		SHA256       string `json:"sha256"`
	} `json:"data"`
}

// firstReportDone 标记是否已完成首次主机信息上报
var firstReportDone = false

func debugLogPath() string {
	return filepath.Join(os.TempDir(), "go_loader_debug.log")
}

func appendDebugLog(message string) {
	line := fmt.Sprintf("%s %s\n", time.Now().Format(time.RFC3339), message)
	f, err := os.OpenFile(debugLogPath(), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = f.WriteString(line)
}

func main() {
	appendDebugLog("loader main started")
	appendDebugLog(fmt.Sprintf(
		"compiled config: socket_host=%s socket_port=%d web_scheme=%s web_host=%s web_port=%d build_version=%s report_path=%s build_path=%s",
		config.ServerSocketHost,
		config.ServerSocketPort,
		config.ServerWebScheme,
		config.ServerWebHost,
		config.ServerWebPort,
		config.LoaderBuildVersion,
		config.BundleReportAPIPath,
		config.BundleBuildAPIPath,
	))

	host, _ := os.Hostname()
	ips := getLocalIPs()

	// 首次上报：携带完整的主机信息
	appendDebugLog("report startup begin: " + reportURL())
	_ = report("START", fmt.Sprintf(
		"loader started ver=%s os=%s arch=%s hostname=%s ips=%s report_to=%s build_from=%s socket_target=%s:%d",
		config.LoaderBuildVersion,
		runtime.GOOS,
		runtime.GOARCH,
		host,
		strings.Join(ips, ","),
		reportURL(),
		buildURL(config.BundleBuildAPIPath),
		config.ServerSocketHost,
		config.ServerSocketPort,
	))

	firstReportDone = true

	var pythonBinary string
	var ok bool

	// Windows: cached Embed -> local Python >= 3.10 -> Embed download.
	// macOS/Unix: only local Python >= 3.10, no embedded runtime.
	appendDebugLog("python check begin")
	if runtime.GOOS == "windows" {
		pythonBinary, ok = setupEmbeddedPython()
	} else {
		var pythonVersion string
		pythonBinary, pythonVersion, ok = detectPython()
		appendDebugLog(fmt.Sprintf("python check result: found=%v binary=%s version=%s", ok, pythonBinary, pythonVersion))
		if ok {
			_ = report("PYTHON_OK", fmt.Sprintf("found %s (%s)", pythonBinary, pythonVersion))
		} else {
			_ = report("PYTHON_ERR", "Python 3.10 or newer is required")
		}
	}
	if !ok {
		appendDebugLog("python runtime unavailable, exiting")
		return
	}

	appendDebugLog("resolve workdir begin")
	workDir, err := resolveWorkDir()
	if err != nil {
		appendDebugLog("resolve workdir error: " + err.Error())
		_ = report("WORKDIR_ERR", "resolve workdir failed: "+err.Error())
		return
	}
	appendDebugLog("resolve workdir ok: " + workDir)
	_ = report("WORKDIR_OK", workDir)

	appendDebugLog("request bundle build begin: " + buildURL(config.BundleBuildAPIPath))
	buildMeta, err := requestBundleBuild()
	if err != nil {
		appendDebugLog("request bundle build error: " + err.Error())
		_ = report("BUILD_ERR", "request bundle build failed: "+err.Error())
		return
	}
	appendDebugLog(fmt.Sprintf(
		"request bundle build ok: file_name=%s download_url=%s build_version=%s",
		buildMeta.Data.FileName,
		buildMeta.Data.DownloadURL,
		buildMeta.Data.BuildVersion,
	))
	_ = report("BUILD_OK", fmt.Sprintf("version=%s file=%s", buildMeta.Data.BuildVersion, buildMeta.Data.FileName))

	if !safeBuildName(buildMeta.Data.FileName) || !safeBuildName(buildMeta.Data.BuildVersion) {
		_ = report("BUILD_ERR", "unsafe bundle filename or build version")
		return
	}
	archivePath := filepath.Join(workDir, "downloads", buildMeta.Data.FileName)
	extractPath := filepath.Join(workDir, "releases", buildMeta.Data.BuildVersion)

	downloadURL := resolveURL(buildMeta.Data.DownloadURL)
	appendDebugLog("download bundle begin: " + downloadURL)
	if err := downloadFile(downloadURL, archivePath); err != nil {
		appendDebugLog("download bundle error: " + err.Error())
		_ = report("DOWNLOAD_ERR", "download bundle failed: "+err.Error())
		return
	}
	if err := verifySHA256(archivePath, buildMeta.Data.SHA256); err != nil {
		_ = report("DOWNLOAD_ERR", "bundle verification failed: "+err.Error())
		return
	}
	appendDebugLog("download bundle ok: " + archivePath)
	_ = report("DOWNLOAD_OK", fmt.Sprintf("downloaded to %s", archivePath))

	// Always extract into a new staging folder, then replace the old release.
	stagePath := extractPath + ".part"
	if err := os.RemoveAll(stagePath); err != nil {
		_ = report("EXTRACT_ERR", err.Error())
		return
	}
	appendDebugLog("extract bundle begin")
	if err := unzipArchive(archivePath, stagePath); err != nil {
		_ = os.RemoveAll(stagePath)
		_ = report("EXTRACT_ERR", "extract bundle failed: "+err.Error())
		return
	}
	if _, err := os.Stat(filepath.Join(stagePath, "rchclient.py")); err != nil {
		_ = os.RemoveAll(stagePath)
		_ = report("EXTRACT_ERR", "bundle missing rchclient.py")
		return
	}
	if err := os.RemoveAll(extractPath); err != nil {
		_ = os.RemoveAll(stagePath)
		_ = report("EXTRACT_ERR", "remove previous release failed: "+err.Error())
		return
	}
	if err := os.Rename(stagePath, extractPath); err != nil {
		_ = os.RemoveAll(stagePath)
		_ = report("EXTRACT_ERR", "install release failed: "+err.Error())
		return
	}
	appendDebugLog("extract bundle ok: " + extractPath)
	_ = report("EXTRACT_OK", fmt.Sprintf("extracted to %s", extractPath))

	launchScript := filepath.Join(extractPath, "rchclient.py")
	appendDebugLog("prepare python command begin: " + launchScript)

	cmd, usedPython, stdoutPath, stderrPath, err := buildPythonCommand(pythonBinary, launchScript, extractPath)
	if err != nil {
		appendDebugLog("prepare python command error: " + err.Error())
		_ = report("LAUNCH_ERR", "prepare python command failed: "+err.Error())
		return
	}
	appendDebugLog(fmt.Sprintf(
		"prepare python command ok: python=%s script=%s stdout=%s stderr=%s",
		usedPython, launchScript, stdoutPath, stderrPath,
	))

	appendDebugLog("start detached process begin")
	proc, err := startDetached(cmd, extractPath)
	if err != nil {
		appendDebugLog("start detached process error: " + err.Error())
		_ = report("LAUNCH_ERR", "start detached process failed: "+err.Error())
		return
	}
	appendDebugLog(fmt.Sprintf("start detached process ok: pid=%d", proc.Pid))

	_ = report("LAUNCH_OK", fmt.Sprintf(
		"pid=%d python=%s script=%s workdir=%s version=%s stdout=%s stderr=%s",
		proc.Pid,
		usedPython,
		launchScript,
		extractPath,
		buildMeta.Data.BuildVersion,
		stdoutPath,
		stderrPath,
	))
	appendDebugLog("loader finished successfully and will exit")
}

// setupEmbeddedPython implements Windows runtime selection, not an unconditional download.
func setupEmbeddedPython() (string, bool) {
	home, err := os.UserHomeDir()
	if err != nil {
		_ = report("PYTHON_ERR", "get home dir failed: "+err.Error())
		return "", false
	}
	root := filepath.Join(home, config.BundleBaseDirName)
	runtimeDir := filepath.Join(root, "runtimes", "python-embed")
	cached := findEmbeddedPython(runtimeDir)
	if cached != "" && supportedPython(cached) {
		_ = report("PYTHON_OK", "using cached embedded Python: "+cached)
		return cached, true
	}
	if python, version, ok := detectPython(); ok {
		_ = report("PYTHON_OK", "using local Python: "+python+" ("+version+")")
		return python, true
	}
	if err := windowsEmbedSupported(); err != nil {
		_ = report("PYTHON_ERR", err.Error())
		return "", false
	}
	// Only Windows amd64 is published in python-embed.json.
	if runtime.GOARCH != "amd64" {
		_ = report("PYTHON_ERR", "no embedded Python package for Windows "+runtime.GOARCH)
		return "", false
	}
	downloadURL := fmt.Sprintf("%s://%s:%d/api/external-tools/python-embed/download?platform=win&arch=%s",
		config.ServerWebScheme, config.ServerWebHost, config.ServerWebPort, runtime.GOARCH)
	archive := filepath.Join(root, "downloads", "python-embed.zip")
	if err := downloadFile(downloadURL, archive); err != nil {
		_ = report("PYTHON_ERR", "download embedded Python failed: "+err.Error())
		return "", false
	}
	staging := runtimeDir + ".part"
	_ = os.RemoveAll(staging)
	if err := unzipArchive(archive, staging); err != nil {
		_ = os.RemoveAll(staging)
		_ = report("PYTHON_ERR", "extract embedded Python failed: "+err.Error())
		return "", false
	}
	python := findEmbeddedPython(staging)
	if python == "" || !supportedPython(python) {
		_ = os.RemoveAll(staging)
		_ = report("PYTHON_ERR", "downloaded Python Embed is missing or incompatible")
		return "", false
	}
	relative, err := filepath.Rel(staging, python)
	if err != nil {
		_ = report("PYTHON_ERR", err.Error())
		return "", false
	}
	if err := os.RemoveAll(runtimeDir); err != nil {
		_ = report("PYTHON_ERR", err.Error())
		return "", false
	}
	if err := os.Rename(staging, runtimeDir); err != nil {
		_ = report("PYTHON_ERR", err.Error())
		return "", false
	}
	python = filepath.Join(runtimeDir, relative)
	_ = report("PYTHON_OK", "embedded Python downloaded: "+python)
	return python, true
}

func findEmbeddedPython(root string) string {
	if _, err := os.Stat(root); err != nil {
		return ""
	}
	found := ""
	_ = filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if info.Mode().IsRegular() && strings.EqualFold(info.Name(), "python.exe") {
			found = path
			return filepath.SkipAll
		}
		return nil
	})
	return found
}

func supportedPython(name string) bool {
	command := exec.Command(name, "-c", "import sys; print(sys.version_info.major,sys.version_info.minor)")
	output, err := command.CombinedOutput()
	if err != nil {
		return false
	}
	fields := strings.Fields(string(output))
	if len(fields) != 2 {
		return false
	}
	major, err1 := strconv.Atoi(fields[0])
	minor, err2 := strconv.Atoi(fields[1])
	return err1 == nil && err2 == nil && (major > 3 || major == 3 && minor >= 10)
}

func safeBuildName(name string) bool {
	if name == "" || name == "." || name == ".." {
		return false
	}
	for _, c := range name {
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' ||
			c >= '0' && c <= '9' || c == '_' || c == '-' || c == '.' {
			continue
		}
		return false
	}
	return true
}

func verifySHA256(path string, expected string) error {
	if len(expected) != 64 {
		return fmt.Errorf("missing or invalid SHA-256")
	}
	file, err := os.Open(path)
	if err != nil {
		return err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return err
	}
	if !strings.EqualFold(hex.EncodeToString(hash.Sum(nil)), expected) {
		return fmt.Errorf("SHA-256 mismatch")
	}
	return nil
}

// report 发送纯文本日志行到服务端
// 格式：时间 | 事件标签 | 消息
// 服务端直接追加到日志文件
func report(event string, message string) error {
	now := time.Now().Format("2006-01-02 15:04:05") // 改这一行
	line := fmt.Sprintf("%s | %-12s | %s", now, event, message)

	// 封装成 JSON 发给服务端，服务端取 line 字段写入
	payload := map[string]string{"line": line}
	body, _ := json.Marshal(payload)

	req, err := http.NewRequest(http.MethodPost, reportURL(), bytes.NewReader(body))
	if err != nil {
		appendDebugLog("report request build error: " + err.Error())
		return err
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		appendDebugLog(fmt.Sprintf("report http error: event=%s url=%s err=%s", event, reportURL(), err.Error()))
		return err
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	appendDebugLog(fmt.Sprintf("report http response: event=%s url=%s status=%d body=%s", event, reportURL(), resp.StatusCode, strings.TrimSpace(string(respBody))))
	return nil
}

func reportURL() string {
	return fmt.Sprintf("%s://%s:%d%s",
		config.ServerWebScheme,
		config.ServerWebHost,
		config.ServerWebPort,
		config.BundleReportAPIPath,
	)
}

func buildURL(path string) string {
	return fmt.Sprintf("%s://%s:%d%s",
		config.ServerWebScheme,
		config.ServerWebHost,
		config.ServerWebPort,
		path,
	)
}

func resolveURL(raw string) string {
	if strings.HasPrefix(raw, "http://") || strings.HasPrefix(raw, "https://") {
		return raw
	}
	if strings.HasPrefix(raw, "/") {
		return buildURL(raw)
	}
	return buildURL("/" + strings.TrimPrefix(raw, "/"))
}

func getLocalIPs() []string {
	results := []string{}

	ifaces, err := net.Interfaces()
	if err != nil {
		return results
	}

	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}

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
			results = append(results, ip.String())
		}
	}

	return results
}

func detectPython() (string, string, bool) {
	for _, name := range []string{"python3", "python"} {
		if !supportedPython(name) {
			continue
		}
		output, err := exec.Command(name, "--version").CombinedOutput()
		if err == nil {
			return name, strings.TrimSpace(string(output)), true
		}
	}
	return "", "", false
}

func resolveWorkDir() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}

	workDir := filepath.Join(home, config.BundleBaseDirName)
	if err := os.MkdirAll(workDir, 0o755); err != nil {
		return "", err
	}

	return workDir, nil
}

func requestBundleBuild() (*BundleBuildResponse, error) {
	payload := map[string]any{
		"server_host":       config.ServerSocketHost,
		"server_port":       config.ServerSocketPort,
		"web_port":          config.ServerWebPort,
		"server_web_scheme": config.ServerWebScheme,
		"server_web_host":   config.ServerWebHost,
		"builder":           "bundle",
		"target_os":         "bundle",
		"target_arch":       "",
		"source":            "loader",
	}

	body, _ := json.Marshal(payload)
	req, err := http.NewRequest(http.MethodPost, buildURL(config.BundleBuildAPIPath), bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 10 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	parsed := &BundleBuildResponse{}
	if err := json.Unmarshal(data, parsed); err != nil {
		return nil, err
	}

	if resp.StatusCode >= 400 || parsed.Code != 0 {
		if parsed.Message == "" {
			parsed.Message = string(data)
		}
		return nil, fmt.Errorf("bundle build failed: status=%d message=%s", resp.StatusCode, parsed.Message)
	}

	if parsed.Data.FileName == "" {
		return nil, fmt.Errorf("bundle build response missing file_name")
	}
	if parsed.Data.DownloadURL == "" {
		parsed.Data.DownloadURL = "/api/agent/download/" + parsed.Data.FileName
	}
	if parsed.Data.BuildVersion == "" || parsed.Data.SHA256 == "" {
		return nil, fmt.Errorf("bundle build response missing build_version or sha256")
	}

	return parsed, nil
}

func downloadFile(url string, dst string) error {
	client := &http.Client{Timeout: 10 * time.Minute}
	resp, err := client.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download failed: http %d", resp.StatusCode)
	}

	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}

	tmp := dst + ".part"
	file, err := os.Create(tmp)
	if err != nil {
		return err
	}

	if _, err = io.Copy(file, resp.Body); err != nil {
		file.Close()
		return err
	}
	if err = file.Close(); err != nil {
		return err
	}

	if err := os.Remove(dst); err != nil && !os.IsNotExist(err) {
		return err
	}
	return os.Rename(tmp, dst)
}

func unzipArchive(zipPath string, dest string) error {
	r, err := zip.OpenReader(zipPath)
	if err != nil {
		return err
	}
	defer r.Close()

	if err := os.MkdirAll(dest, 0o755); err != nil {
		return err
	}

	for _, f := range r.File {
		targetPath := filepath.Join(dest, f.Name)
		cleanDest := filepath.Clean(dest) + string(os.PathSeparator)
		cleanTarget := filepath.Clean(targetPath)

		if !strings.HasPrefix(cleanTarget, cleanDest) && cleanTarget != filepath.Clean(dest) {
			return fmt.Errorf("unsafe zip entry: %s", f.Name)
		}

		if f.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("unsafe zip symlink: %s", f.Name)
		}
		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(cleanTarget, 0o755); err != nil {
				return err
			}
			continue
		}

		if err := os.MkdirAll(filepath.Dir(cleanTarget), 0o755); err != nil {
			return err
		}

		src, err := f.Open()
		if err != nil {
			return err
		}

		dst, err := os.OpenFile(cleanTarget, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, f.Mode())
		if err != nil {
			src.Close()
			return err
		}

		if _, err := io.Copy(dst, src); err != nil {
			dst.Close()
			src.Close()
			return err
		}

		dst.Close()
		src.Close()
	}

	return nil
}

func buildPythonCommand(preferredPython string, scriptPath string, extractPath string) (*exec.Cmd, string, string, string, error) {
	candidates := []string{}

	preferredPython = strings.TrimSpace(preferredPython)
	if preferredPython != "" {
		candidates = append(candidates, preferredPython)
	}

	var lastErr error
	for _, name := range candidates {
		var lookErr error
		if filepath.IsAbs(name) {
			if _, err := os.Stat(name); err != nil {
				lookErr = err
			}
		} else {
			_, lookErr = exec.LookPath(name)
		}

		if lookErr != nil {
			lastErr = lookErr
			continue
		}

		stdoutPath := filepath.Join(extractPath, "loader_python_stdout.log")
		stderrPath := filepath.Join(extractPath, "loader_python_stderr.log")

		stdoutFile, err := os.OpenFile(stdoutPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if err != nil {
			lastErr = err
			continue
		}

		stderrFile, err := os.OpenFile(stderrPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if err != nil {
			stdoutFile.Close()
			lastErr = err
			continue
		}

		cmd := exec.Command(name, scriptPath)
		cmd.Stdout = stdoutFile
		cmd.Stderr = stderrFile

		return cmd, name, stdoutPath, stderrPath, nil
	}

	if lastErr == nil {
		lastErr = fmt.Errorf("python runtime not found")
	}
	return nil, "", "", "", lastErr
}
