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
	if !safeBuildName("source-bundle-20261016") {
		t.Fatal("valid build version rejected")
	}
}
