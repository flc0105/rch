package executor

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"client-go/protocol"
)

func sessionForShutdownTest(t *testing.T) (*Session, func()) {
	t.Helper()
	left, right := net.Pipe()
	result := NewSession(protocol.NewRATSocket(left), "shutdown-test")
	done := make(chan struct{})
	go func() {
		defer close(done)
		server := protocol.NewRATSocket(right)
		for {
			if _, err := server.Recv(); err != nil {
				return
			}
		}
	}()
	return result, func() { _ = left.Close(); _ = right.Close(); <-done }
}

func assertNoTransferFiles(t *testing.T, dir string) {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil && !os.IsNotExist(err) {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("interrupted transfer left files: %v", entries)
	}
}

func TestHTTPManagedDownloadStopsAtSessionDisconnect(t *testing.T) {
	started := make(chan struct{}, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started <- struct{}{}
		<-r.Context().Done()
	}))
	defer server.Close()
	session, cleanup := sessionForShutdownTest(t)
	defer cleanup()
	if err := session.SetServerWebBaseURL(server.URL); err != nil {
		t.Fatal(err)
	}
	folder := filepath.Join(t.TempDir(), "http-download")
	session.StartTransfer("http", "server_to_client_file", map[string]interface{}{
		"relative_url": "/pending", "filename": "pending.bin", "save_dir": folder,
	})
	select {
	case <-started:
	case <-time.After(2 * time.Second):
		t.Fatal("HTTP download did not begin")
	}
	finished := make(chan struct{})
	go func() { session.Close(); close(finished) }()
	select {
	case <-finished:
	case <-time.After(2 * time.Second):
		t.Fatal("HTTP worker did not stop when its session closed")
	}
	assertNoTransferFiles(t, folder)
}

func TestTCPManagedDownloadStopsAtSessionDisconnect(t *testing.T) {
	session, cleanup := sessionForShutdownTest(t)
	defer cleanup()
	session.SetSessionToken("active-token")
	entered := make(chan struct{}, 1)
	session.SetFileDataOpener(func(ctx context.Context, id, token string, _ func()) (net.Conn, error) {
		if id != "tcp" || token != "active-token" {
			t.Errorf("unexpected transfer token: %q %q", id, token)
		}
		client, peer := net.Pipe()
		go func() {
			defer peer.Close()
			_ = writeFileControl(peer, map[string]interface{}{"ok": true})
			_ = writeFileControl(peer, map[string]interface{}{"size": 4096})
			_ = writeFileBytes(peer, []byte("some bytes"))
			entered <- struct{}{}
			// Waiting on cancellation closes the data socket, releasing the peer.
			var b [1]byte
			_, _ = peer.Read(b[:])
		}()
		return client, nil
	})
	folder := filepath.Join(t.TempDir(), "tcp-download")
	ctx, cancel := context.WithCancel(context.Background())
	if !session.transfers.start("tcp", cancel) {
		t.Fatal("unable to register TCP worker")
	}
	go func() {
		defer cancel()
		defer session.transfers.finish("tcp")
		_ = session.downloadTransferFileTCP(ctx, "tcp", map[string]interface{}{
			"filename": "pending.bin", "save_dir": folder,
		})
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("TCP transfer did not begin")
	}
	finished := make(chan struct{})
	go func() { session.Close(); close(finished) }()
	select {
	case <-finished:
	case <-time.After(2 * time.Second):
		t.Fatal("TCP worker did not stop when its session closed")
	}
	assertNoTransferFiles(t, folder)
}
