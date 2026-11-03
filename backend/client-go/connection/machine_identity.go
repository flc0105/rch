package connection

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

// machineComponents follows core/device/machine_identity.py's v1 fingerprint fields.
// Keep raw architecture and OS version here; the handshake may normalize arch separately.
type machineComponents struct {
	hostname     string
	osName       string
	osVersion    string
	arch         string
	manufacturer string
	model        string
	nativeID     string
}

type hostIdentity struct {
	machineComponents
	osType           string
	osAlias          string
	osFull           string
	handshakeArch    string
	machineID        string
	fingerprintBasis string
}

func normalizeFingerprintValue(value string) string {
	text := strings.ToLower(strings.TrimSpace(value))
	if text == "" {
		return "na"
	}
	var b strings.Builder
	previousUnderscore := false
	for _, r := range text {
		allowed := (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '.' || r == ':' || r == '-'
		if allowed {
			b.WriteRune(r)
			previousUnderscore = false
		} else if !previousUnderscore {
			b.WriteByte('_')
			previousUnderscore = true
		}
	}
	if result := strings.Trim(b.String(), "_"); result != "" {
		return result
	}
	return "na"
}

func normalizeFingerprintOSVersion(value string) string {
	text := strings.TrimSpace(value)
	if text == "" {
		return "na"
	}
	// Python searches for the first \d+(?:\.\d+)+, then the first \d+.
	// Only ASCII decimal digits participate in this version pattern.
	firstNumber := -1
	for i := 0; i < len(text); i++ {
		if text[i] >= '0' && text[i] <= '9' {
			firstNumber = i
			break
		}
	}
	if firstNumber < 0 {
		return normalizeFingerprintValue(text)
	}
	for start := firstNumber; start < len(text); start++ {
		if text[start] < '0' || text[start] > '9' {
			continue
		}
		end := start
		for end < len(text) && text[end] >= '0' && text[end] <= '9' {
			end++
		}
		segments := end
		for segments+1 < len(text) && text[segments] == '.' && text[segments+1] >= '0' && text[segments+1] <= '9' {
			segments++
			for segments < len(text) && text[segments] >= '0' && text[segments] <= '9' {
				segments++
			}
		}
		if segments > end {
			return normalizeFingerprintValue(text[start:segments])
		}
	}
	end := firstNumber
	for end < len(text) && text[end] >= '0' && text[end] <= '9' {
		end++
	}
	return normalizeFingerprintValue(text[firstNumber:end])
}

func machineFingerprint(raw machineComponents) (string, string) {
	basis := "v1" +
		"|hostname=" + normalizeFingerprintValue(raw.hostname) +
		"|os_name=" + normalizeFingerprintValue(raw.osName) +
		"|os_version=" + normalizeFingerprintOSVersion(raw.osVersion) +
		"|arch=" + normalizeFingerprintValue(raw.arch) +
		"|manufacturer=" + normalizeFingerprintValue(raw.manufacturer) +
		"|model=" + normalizeFingerprintValue(raw.model) +
		"|native_id=" + normalizeFingerprintValue(raw.nativeID)
	hash := sha256.Sum256([]byte(basis))
	return hex.EncodeToString(hash[:]), basis
}

func detectHostIdentity() hostIdentity {
	id := hostIdentity{}
	id.hostname, _ = os.Hostname()
	id.arch = detectMachineArch()
	switch runtime.GOOS {
	case "windows":
		id.osType, id.osAlias, id.osName = "Windows", "win", "Windows"
		win := detectWindowsIdentity()
		id.osVersion = win.Version
		id.manufacturer = cleanHardwareValue(win.Manufacturer)
		id.model = cleanHardwareValue(win.Model)
		id.nativeID = win.NativeID
	case "darwin":
		id.osType, id.osAlias, id.osName = "macOS", "mac", "macOS"
		id.osVersion = commandText("/usr/bin/sw_vers", "-productVersion")
		id.manufacturer = "Apple"
		id.model = commandText("/usr/sbin/sysctl", "-n", "hw.model")
		id.nativeID = macPlatformUUID()
	case "linux":
		id.osType, id.osAlias = "Linux", "linux"
		id.osName, id.osVersion = linuxDistribution()
		id.manufacturer = cleanHardwareValue(readFirstFile("/sys/devices/virtual/dmi/id/sys_vendor", "/sys/class/dmi/id/sys_vendor"))
		id.model = cleanHardwareValue(readFirstFile("/sys/devices/virtual/dmi/id/product_name", "/sys/class/dmi/id/product_name"))
		id.nativeID = readFirstFile("/etc/machine-id", "/var/lib/dbus/machine-id")
	default:
		id.osType, id.osAlias, id.osName = runtime.GOOS, runtime.GOOS, runtime.GOOS
	}
	if id.osVersion == "" {
		id.osVersion = commandText("uname", "-r")
	}
	id.handshakeArch = normalizeHandshakeArch(id.arch)
	id.osFull = id.osType + "-" + id.osVersion + "-" + id.arch
	id.machineID, id.fingerprintBasis = machineFingerprint(id.machineComponents)
	return id
}

func normalizeHandshakeArch(raw string) string {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "x86_64", "x64":
		return "amd64"
	case "aarch64":
		return "arm64"
	case "i386", "i686", "x86":
		return "386"
	default:
		return strings.ToLower(strings.TrimSpace(raw))
	}
}

func detectMachineArch() string {
	if runtime.GOOS == "windows" {
		if value := strings.TrimSpace(os.Getenv("PROCESSOR_ARCHITEW6432")); value != "" {
			return value
		}
		if value := strings.TrimSpace(os.Getenv("PROCESSOR_ARCHITECTURE")); value != "" {
			return value
		}
		return runtime.GOARCH
	}
	for _, uname := range []string{"/usr/bin/uname", "/bin/uname", "uname"} {
		if value := commandText(uname, "-m"); value != "" {
			return value
		}
	}
	if runtime.GOARCH == "amd64" {
		return "x86_64"
	}
	if runtime.GOOS == "linux" && runtime.GOARCH == "arm64" {
		return "aarch64"
	}
	return runtime.GOARCH
}

func commandText(name string, args ...string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, name, args...).Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func readFirstFile(paths ...string) string {
	for _, path := range paths {
		if data, err := os.ReadFile(path); err == nil {
			return strings.TrimSpace(string(data))
		}
	}
	return ""
}

func linuxDistribution() (string, string) {
	name, version, fallbackName, fallbackVersion := "", "", "", ""
	for _, line := range strings.Split(readFirstFile("/etc/os-release", "/usr/lib/os-release"), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		value = strings.Trim(strings.TrimSpace(value), `"'`)
		switch strings.TrimSpace(key) {
		case "NAME":
			name = value
		case "ID":
			fallbackName = value
		case "VERSION_ID":
			version = value
		case "VERSION":
			fallbackVersion = value
		}
	}
	if name == "" {
		name = fallbackName
	}
	if name == "" {
		name = "Linux"
	}
	if version == "" {
		version = fallbackVersion
	}
	if version == "" {
		version = commandText("uname", "-r")
	}
	return name, version
}

func cleanHardwareValue(value string) string {
	value = strings.TrimSpace(value)
	switch strings.ToLower(value) {
	case "to be filled by o.e.m.", "to be filled by oem", "default string", "system manufacturer", "system product name", "unknown", "n/a", "na", "none":
		return ""
	default:
		return value
	}
}

func macPlatformUUID() string {
	output := commandText("/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice")
	for _, line := range strings.Split(output, "\n") {
		if !strings.Contains(line, `"IOPlatformUUID"`) {
			continue
		}
		_, after, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		return strings.Trim(strings.TrimSpace(after), `"`)
	}
	return ""
}

type windowsIdentity struct {
	Version      string `json:"version"`
	Manufacturer string `json:"manufacturer"`
	Model        string `json:"model"`
	NativeID     string `json:"native_id"`
}

func detectWindowsIdentity() windowsIdentity {
	// Use the same SMBIOS and MachineGuid registry locations as Python.
	const script = `$ErrorActionPreference='Stop'; ` +
		`[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding; ` +
		`$OutputEncoding=[Console]::OutputEncoding; ` +
		`$bios=Get-ItemProperty -Path 'HKLM:\HARDWARE\DESCRIPTION\System\BIOS' -ErrorAction SilentlyContinue; ` +
		`$crypt=Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Cryptography' -ErrorAction SilentlyContinue; ` +
		`$man=$bios.SystemManufacturer; $model=$bios.SystemProductName; ` +
		`$bad=@('to be filled by o.e.m.','to be filled by oem','default string','system manufacturer','system product name','unknown','n/a','na','none'); ` +
		`if ($man -and $bad.Contains(([string]$man).Trim().ToLowerInvariant())) {$man=$null}; ` +
		`if ($model -and $bad.Contains(([string]$model).Trim().ToLowerInvariant())) {$model=$null}; ` +
		`if (-not $man -or -not $model) { $sys=Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue; ` +
		`if (-not $man) {$man=$sys.Manufacturer}; if (-not $model) {$model=$sys.Model} }; ` +
		`[pscustomobject]@{version=[Environment]::OSVersion.Version.ToString(3); manufacturer=$man; model=$model; native_id=$crypt.MachineGuid} | ConvertTo-Json -Compress`
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script)
	hideCommandWindow(cmd)
	out, err := cmd.Output()
	if err != nil {
		return windowsIdentity{}
	}
	var info windowsIdentity
	if err := json.Unmarshal([]byte(strings.TrimPrefix(strings.TrimSpace(string(out)), "\ufeff")), &info); err != nil {
		return windowsIdentity{}
	}
	return info
}
