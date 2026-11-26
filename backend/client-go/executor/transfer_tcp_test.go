package executor

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"client-go/protocol"
)

func transferTestSession(t *testing.T, handle func(net.Conn)) (*Session, func()) {
	t.Helper()
	messageClient, messageServer := net.Pipe()
	session := NewSession(protocol.NewRATSocket(messageClient), "test-client")
	session.SetSessionToken("session-secret")
	done := make(chan struct{})
	go func() {
		defer close(done)
		peer := protocol.NewRATSocket(messageServer)
		for {
			if _, err := peer.Recv(); err != nil {
				return
			}
		}
	}()
	session.SetFileDataOpener(func(_ context.Context, id, token string, _ func()) (net.Conn, error) {
		if token != "session-secret" {
			return nil, fmt.Errorf("bad token")
		}
		client, server := net.Pipe()
		go func() { defer server.Close(); handle(server) }()
		return client, nil
	})
	return session, func() { messageClient.Close(); messageServer.Close(); <-done }
}

func TestTCPManagedUploadWithChecksumAndAck(t *testing.T) {
	folder := t.TempDir()
	path := filepath.Join(folder, "传输.txt")
	payload := bytes.Repeat([]byte("hello-file"), 6500)
	if err := os.WriteFile(path, payload, 0600); err != nil {
		t.Fatal(err)
	}
	received := make(chan error, 1)
	session, done := transferTestSession(t, func(sock net.Conn) {
		if err := writeFileControl(sock, map[string]interface{}{"ok": true}); err != nil {
			received <- err
			return
		}
		header, err := receiveFileControl(sock)
		if err != nil {
			received <- err
			return
		}
		tmp, err := os.CreateTemp(folder, "server-")
		if err != nil {
			received <- err
			return
		}
		defer tmp.Close()
		_, err = receiveTCPFile(context.Background(), sock, tmp, header, nil)
		if err != nil {
			received <- err
			return
		}
		b, err := os.ReadFile(tmp.Name())
		if err != nil {
			received <- err
			return
		}
		if !bytes.Equal(payload, b) || header["filename"] != "传输.txt" || header["artifact_type"] != "saved" {
			received <- fmt.Errorf("payload mismatch")
			return
		}
		received <- writeFileControl(sock, map[string]interface{}{"ok": true, "data": map[string]interface{}{"artifact_id": "abc-123"}})
	})
	defer done()
	if err := session.uploadTransferFileTCP(context.Background(), "transfer1", path, "传输.txt", "saved", "downloads"); err != nil {
		t.Fatal(err)
	}
	if err := <-received; err != nil {
		t.Fatal(err)
	}
}

func TestTCPManagedDownloadAndConflictPolicy(t *testing.T) {
	root := t.TempDir()
	content := bytes.Repeat([]byte("binary\x00data"), 10000)
	checksum := sha256.Sum256(content)
	session, done := transferTestSession(t, func(sock net.Conn) {
		if err := writeFileControl(sock, map[string]interface{}{"ok": true}); err != nil {
			t.Error(err)
			return
		}
		if err := writeFileControl(sock, map[string]interface{}{"size": len(content)}); err != nil {
			t.Error(err)
			return
		}
		if err := writeFileBytes(sock, content); err != nil {
			t.Error(err)
			return
		}
		if err := writeFileControl(sock, map[string]interface{}{"sha256": hex.EncodeToString(checksum[:])}); err != nil {
			t.Error(err)
			return
		}
		ack, err := receiveFileControl(sock)
		if err != nil || ack["ok"] != true || ack["size"] != float64(len(content)) {
			t.Errorf("invalid ack: %v %v", ack, err)
		}
	})
	defer done()
	session.Cwd = root
	payload := map[string]interface{}{"filename": "download.bin", "save_dir": root, "conflict_policy": "stop"}
	if err := session.downloadTransferFileTCP(context.Background(), "transfer2", payload); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(root, "download.bin"))
	if err != nil || !bytes.Equal(got, content) {
		t.Fatal("file changed")
	}
	if err := session.downloadTransferFileTCP(context.Background(), "transfer3", payload); err == nil {
		t.Fatal("overwrote existing file")
	}
}

func TestTCPControlChecksumAndAuthenticationFailures(t *testing.T) {
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()
	go func() {
		_ = writeFileControl(left, map[string]interface{}{"size": 3})
		_ = writeFileBytes(left, []byte("abc"))
		_ = writeFileControl(left, map[string]interface{}{"sha256": "wrong"})
	}()
	tmp, err := os.CreateTemp(t.TempDir(), "incoming-")
	if err != nil {
		t.Fatal(err)
	}
	defer tmp.Close()
	head, err := receiveFileControl(right)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = receiveTCPFile(context.Background(), right, tmp, head, nil); err == nil {
		t.Fatal("accepted invalid checksum")
	}
	session := NewSession(nil, "test")
	session.SetFileDataOpener(func(_ context.Context, _, _ string, _ func()) (net.Conn, error) { return nil, nil })
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if _, err = session.openFileData(ctx, "x"); err == nil {
		t.Fatal("accepted missing session token")
	}
}

func TestTCPZeroByteFileRoundTrip(t *testing.T) {
	root := t.TempDir()
	empty := filepath.Join(root, "empty.bin")
	if err := os.WriteFile(empty, nil, 0600); err != nil {
		t.Fatal(err)
	}
	sender, receiver := net.Pipe()
	defer sender.Close()
	defer receiver.Close()
	done := make(chan error, 1)
	go func() {
		header, err := receiveFileControl(receiver)
		if err != nil {
			done <- err
			return
		}
		output, err := os.CreateTemp(root, "zero-")
		if err != nil {
			done <- err
			return
		}
		defer output.Close()
		n, err := receiveTCPFile(context.Background(), receiver, output, header, nil)
		if err == nil && n != 0 {
			err = fmt.Errorf("received %d bytes for empty file", n)
		}
		done <- err
	}()
	n, err := sendTCPFile(context.Background(), sender, empty, nil, nil)
	if err != nil || n != 0 {
		t.Fatalf("empty send failed: %d %v", n, err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}
