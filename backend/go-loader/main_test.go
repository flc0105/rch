package main

import (
	"archive/zip"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
)

func TestBundleVerificationAndExtraction(t *testing.T) {
	dir := t.TempDir()
	zipPath := filepath.Join(dir, "bundle.zip")
	f, err := os.Create(zipPath)
	if err != nil {
		t.Fatal(err)
	}
	z := zip.NewWriter(f)
	entry, err := z.Create("rchclient.py")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = entry.Write([]byte("pass\n"))
	if err := z.Close(); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(zipPath)
	sum := sha256.Sum256(data)
	if err := verifySHA256(zipPath, hex.EncodeToString(sum[:])); err != nil {
		t.Fatal(err)
	}
	if err := verifySHA256(zipPath, "f"+hex.EncodeToString(sum[:])[1:]); err == nil {
		t.Fatal("incorrect digest accepted")
	}
	extracted := filepath.Join(dir, "releases", "build-1")
	if err := unzipArchive(zipPath, extracted); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(extracted, "rchclient.py")); err != nil {
		t.Fatal(err)
	}
}

func TestZipSlipRejected(t *testing.T) {
	path := filepath.Join(t.TempDir(), "bad.zip")
	f, _ := os.Create(path)
	z := zip.NewWriter(f)
	e, _ := z.Create("../escape.txt")
	_, _ = e.Write([]byte("bad"))
	_ = z.Close()
	_ = f.Close()
	if err := unzipArchive(path, path+".out"); err == nil {
		t.Fatal("zip slip accepted")
	}
}

func TestBuildNamesMustNotEscapeReleaseRoot(t *testing.T) {
	for _, name := range []string{"", ".", "..", "../root", `..\root`, "/absolute", "a/b"} {
		if safeBuildName(name) {
			t.Fatalf("unsafe name accepted: %q", name)
		}
	}
	if !safeBuildName("python_20261106_175136_0e8ae4f2") {
		t.Fatal("valid build version rejected")
	}
}

func TestBundleBuildPayloadListenerSelection(t *testing.T) {
	defaultPayload := bundleBuildPayload("")
	if _, exists := defaultPayload["listener_id"]; exists {
		t.Fatal("default TCP request must remain unchanged")
	}
	tlsPayload := bundleBuildPayload("tls-abc123")
	if tlsPayload["listener_id"] != "tls-abc123" {
		t.Fatalf("TLS listener not forwarded: %#v", tlsPayload)
	}
	if tlsPayload["builder"] != "python" || tlsPayload["server_port"] != 9999 {
		t.Fatal("existing bundle fields changed")
	}
}

func TestLoaderBuildPayloadFourModes(t *testing.T) {
	for _, mode := range []string{"reverse", "bind"} {
		for _, transport := range []string{"tcp", "mtls_tcp"} {
			t.Run(mode+"/"+transport, func(t *testing.T) {
				payload := bundleBuildPayloadFor(mode, transport, "0.0.0.0", 19445, "listener-abc")
				if payload["builder"] != "python" {
					t.Fatal("Go loader must build Python Client")
				}
				if mode == "reverse" {
					if payload["listener_id"] != "listener-abc" {
						t.Fatal("Reverse lost Listener ID")
					}
					if _, ok := payload["server_transport"]; ok {
						t.Fatal("Reverse sent redundant transport")
					}
					if _, ok := payload["bind_port"]; ok {
						t.Fatal("Reverse sent Bind parameters")
					}
				} else {
					if payload["bind_host"] != "0.0.0.0" || payload["bind_port"] != 19445 {
						t.Fatal("Bind endpoint missing")
					}
					if _, ok := payload["listener_id"]; ok {
						t.Fatal("Bind sent Listener ID")
					}
					if _, ok := payload["server_host"]; ok {
						t.Fatal("Bind sent Server socket host")
					}
					_, sent := payload["server_transport"]
					if sent != (transport == "mtls_tcp") {
						t.Fatalf("incorrect transport field: %#v", payload)
					}
					if transport == "mtls_tcp" && payload["server_transport"] != "mtls_tcp" {
						t.Fatal("wrong mTLS transport")
					}
				}
			})
		}
	}
}
