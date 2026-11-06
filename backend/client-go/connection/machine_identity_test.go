package connection

import (
	"os"
	"runtime"
	"strings"
	"testing"
)

func TestFingerprintMatchesPythonV1Vectors(t *testing.T) {
	// These expected values come from core.device.machine_identity.build_machine_identity_payload.
	vectors := []struct {
		name, wantBasis, wantHash string
		raw                       machineComponents
	}{
		{
			name:      "windows",
			raw:       machineComponents{hostname: "DESKTOP-OANT55M", osName: "Windows", osVersion: "Microsoft Windows [Version 10.0.26100.1]", arch: "AMD64", manufacturer: "LENOVO", model: "ThinkPad T14", nativeID: "ABC-123-XYZ"},
			wantBasis: "v1|hostname=desktop-oant55m|os_name=windows|os_version=10.0.26100.1|arch=amd64|manufacturer=lenovo|model=thinkpad_t14|native_id=abc-123-xyz",
			wantHash:  "2d2dd3ece9177343a4a495bfe5a46a86ef135b566296734462109e89358ac48a",
		},
		{
			name:      "mac",
			raw:       machineComponents{hostname: "flcMacBook-Air.local", osName: "macOS", osVersion: "15.2.1", arch: "arm64", manufacturer: "Apple", model: "MacBookAir10,1", nativeID: "A012-34BC"},
			wantBasis: "v1|hostname=flcmacbook-air.local|os_name=macos|os_version=15.2.1|arch=arm64|manufacturer=apple|model=macbookair10_1|native_id=a012-34bc",
			wantHash:  "10044acccaf68547ca9cb251d40df3a00b445fbda6d91c66f04f112f41a281a8",
		},
		{
			name:      "linux",
			raw:       machineComponents{hostname: "My Linux Node", osName: "Ubuntu", osVersion: "22.04", arch: "x86_64", nativeID: "ab:cd_ EF"},
			wantBasis: "v1|hostname=my_linux_node|os_name=ubuntu|os_version=22.04|arch=x86_64|manufacturer=na|model=na|native_id=ab:cd_ef",
			wantHash:  "92ce5e723befd63b6afb629fda20789097f512e0f815dae3932f6447e282e8f5",
		},
	}
	for _, vector := range vectors {
		t.Run(vector.name, func(t *testing.T) {
			gotHash, gotBasis := machineFingerprint(vector.raw)
			if gotBasis != vector.wantBasis || gotHash != vector.wantHash {
				t.Fatalf("fingerprint mismatch:\n basis: %s\n hash: %s", gotBasis, gotHash)
			}
		})
	}
}

func TestFingerprintVersionPrefersDottedDigits(t *testing.T) {
	if got := normalizeFingerprintOSVersion("Windows 2026 build 10.0.26100"); got != "10.0.26100" {
		t.Fatalf("expected first dotted numeric version, got %q", got)
	}
	if got := normalizeFingerprintOSVersion("no version"); got != "no_version" {
		t.Fatalf("expected text fallback, got %q", got)
	}
}

func TestHandshakeFieldsAndCapabilities(t *testing.T) {
	id := detectHostIdentity()
	c := &Client{clientID: "go-test-id", identity: id}
	payload := c.buildHandshake("/some/workspace")
	required := []string{
		"machine_id", "machine_fingerprint_basis", "os_type", "os_alias", "os_name", "os_ver",
		"arch", "manufacturer", "model", "process_id", "username", "process_name", "launch_command",
		"feature_manifest", "variable_manifest", "system_paths", "command_manifest",
	}
	for _, key := range required {
		if _, ok := payload[key]; !ok {
			t.Errorf("missing handshake key %q", key)
		}
	}
	if payload["machine_id"] != id.machineID || payload["machine_fingerprint_basis"] != id.fingerprintBasis {
		t.Fatal("machine identity does not match cached fingerprint")
	}
	if !strings.HasPrefix(payload["machine_fingerprint_basis"].(string), "v1|") || len(payload["machine_id"].(string)) != 64 {
		t.Fatal("invalid machine fingerprint shape")
	}
	if payload["os_type"] == runtime.GOOS && runtime.GOOS != "linux" {
		t.Fatalf("os_type should be a display name rather than GOOS: %v", payload["os_type"])
	}
	if _, ok := payload["launch_mode"]; ok {
		t.Fatal("launch mode was not requested")
	}
	if _, ok := payload["launch_source"]; ok {
		t.Fatal("launch source was not requested")
	}
	if features, ok := payload["feature_manifest"].(map[string]bool); !ok || len(features) < 10 {
		t.Fatalf("feature manifest missing: %#v", payload["feature_manifest"])
	} else {
		if !features["remote_files"] {
			t.Error("remote_files must be enabled for basic file management")
		}
		for name, allowed := range features {
			if name != "remote_files" && allowed {
				t.Errorf("unsupported feature %q is enabled", name)
			}
		}
	}
	if v, ok := payload["variable_manifest"].([]interface{}); !ok || len(v) != 0 {
		t.Fatalf("variable manifest must be []: %#v", payload["variable_manifest"])
	}
	if paths, ok := payload["system_paths"].(map[string]string); !ok {
		t.Fatalf("system paths must be object: %#v", payload["system_paths"])
	} else {
		for _, name := range []string{"root", "home", "desktop", "documents", "downloads", "temp", "executable"} {
			if paths[name] == "" {
				t.Errorf("missing Quick Jump system path %q", name)
			}
		}
	}
	if pid, ok := payload["process_id"].(int); !ok || pid != os.Getpid() {
		t.Fatalf("unexpected process PID: %#v", payload["process_id"])
	}
	if payload["process_name"] == "" || payload["launch_command"] == "" {
		t.Fatal("missing process name or launch command")
	}
	if got := payload["command_manifest"].([]interface{}); len(got) == 0 {
		t.Fatal("existing command manifest must be preserved")
	}
}
