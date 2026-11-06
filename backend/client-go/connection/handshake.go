package connection

import (
	"os"
	"os/user"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"

	"client-go/config"
	"client-go/executor"
)

var unsupportedFeatures = []string{
	"external_tool", "process_monitor", "pty", "screen_view", "screen_input",
	"clipboard", "watchdog", "jobs",
}

func featureManifest() map[string]bool {
	manifest := make(map[string]bool, len(unsupportedFeatures)+1)
	for _, name := range unsupportedFeatures {
		manifest[name] = false
	}
	manifest["remote_files"] = true
	manifest["scripts"] = true
	return manifest
}

// Handshake paths provide the existing Remote Files Quick Jump locations.
func systemPaths() map[string]string {
	home, _ := os.UserHomeDir()
	root := string(filepath.Separator)
	if runtime.GOOS == "windows" {
		root = filepath.VolumeName(home) + string(filepath.Separator)
		if root == string(filepath.Separator) {
			root = `C:\`
		}
	}
	executable, _ := os.Executable()
	paths := map[string]string{
		"root": root,
		"temp": os.TempDir(),
	}
	if home != "" {
		paths["home"] = home
		paths["desktop"] = filepath.Join(home, "Desktop")
		paths["documents"] = filepath.Join(home, "Documents")
		paths["downloads"] = filepath.Join(home, "Downloads")
	}
	if executable != "" {
		paths["executable"] = filepath.Dir(executable)
	}
	return paths
}

func processDetails() (username, processName, launchCommand string) {
	if account, err := user.Current(); err == nil {
		username = account.Username
	}
	if username == "" {
		username = strings.TrimSpace(os.Getenv("USERNAME"))
		if username == "" {
			username = strings.TrimSpace(os.Getenv("USER"))
		}
	}
	path, err := os.Executable()
	if err != nil {
		return username, "", ""
	}
	processName = filepath.Base(path)
	parts := append([]string{path}, os.Args[1:]...)
	for i, arg := range parts {
		parts[i] = quoteLaunchArg(arg)
	}
	launchCommand = strings.Join(parts, " ")
	return
}

func quoteLaunchArg(arg string) string {
	if arg != "" && !strings.ContainsAny(arg, " \t\n\"") {
		return arg
	}
	if runtime.GOOS != "windows" {
		return strconv.Quote(arg)
	}
	// Windows CreateProcess quoting: preserve path separators and trailing backslashes.
	var b strings.Builder
	b.WriteByte('"')
	slashes := 0
	for _, r := range arg {
		switch r {
		case '\\':
			slashes++
		case '"':
			b.WriteString(strings.Repeat(`\`, slashes*2+1))
			b.WriteRune(r)
			slashes = 0
		default:
			b.WriteString(strings.Repeat(`\`, slashes))
			b.WriteRune(r)
			slashes = 0
		}
	}
	b.WriteString(strings.Repeat(`\`, slashes*2))
	b.WriteByte('"')
	return b.String()
}

func (c *Client) buildHandshake(cwd string) map[string]interface{} {
	identity := c.identity
	username, processName, launchCommand := processDetails()
	return map[string]interface{}{
		"type":                      "info",
		"id":                        c.clientID,
		"hostname":                  identity.hostname,
		"machine_id":                identity.machineID,
		"machine_fingerprint_basis": identity.fingerprintBasis,
		"os_type":                   identity.osType,
		"os_alias":                  identity.osAlias,
		"os_name":                   identity.osName,
		"os_full":                   identity.osFull,
		"os_ver":                    identity.osVersion,
		"arch":                      identity.handshakeArch,
		"manufacturer":              identity.manufacturer,
		"model":                     identity.model,
		"cwd":                       cwd,
		"integrity":                 executor.DetectHandshakeIntegrity(),
		"build_version":             config.CLIENT_BUILD_VERSION,
		"go_version":                runtime.Version(),
		"process_id":                os.Getpid(),
		"username":                  username,
		"process_name":              processName,
		"launch_command":            launchCommand,
		"launch_mode":               c.launch.mode,
		"launch_source":             c.launch.source,
		"command_manifest":          executor.CommandManifest(),
		"feature_manifest":          featureManifest(),
		"variable_manifest":         []interface{}{},
		"system_paths":              systemPaths(),
	}
}
