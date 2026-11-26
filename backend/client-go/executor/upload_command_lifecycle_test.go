package executor

import (
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"client-go/protocol"
)

func TestRegisteredCommandUploadStopsWithItsSession(t *testing.T) {
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()
	session := NewSession(protocol.NewRATSocket(left), "command-test")
	root := t.TempDir()
	path := filepath.Join(root, "payload.bin")
	if err := os.WriteFile(path, []byte("payload"), 0600); err != nil {
		t.Fatal(err)
	}
	session.CurrentCommandID = 24
	registrationRead := make(chan struct{})
	go func() {
		peer := protocol.NewRATSocket(right)
		packet, err := peer.Recv()
		if err == nil && packet["type"] == "transfer_register" {
			close(registrationRead)
		}
		// Do not send the registration reply; session teardown must cancel it.
		_, _ = peer.Recv()
	}()
	finished := make(chan error, 1)
	go func() {
		_, err := session.uploadCommandFileTCP(path, "downloads")
		finished <- err
	}()
	select {
	case <-registrationRead:
	case <-time.After(time.Second):
		t.Fatal("command transfer registration did not reach Server")
	}
	_ = session.Sock.Close()
	closeDone := make(chan struct{})
	go func() { session.CloseTransfers(); close(closeDone) }()
	select {
	case <-closeDone:
	case <-time.After(time.Second):
		t.Fatal("command upload survived session closure")
	}
	select {
	case err := <-finished:
		if err == nil || !strings.Contains(err.Error(), "canceled") {
			t.Fatalf("expected canceled command upload, got %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("command upload did not stop")
	}
	if _, err := session.uploadCommandFileTCP(path, "downloads"); err == nil || !strings.Contains(err.Error(), "session is closed") {
		t.Fatalf("closed session accepted command upload: %v", err)
	}
}
