package connection

import (
	"crypto/sha256"
	"encoding/hex"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"client-go/config"
)

func withServerConfig(t *testing.T, addr, transport, fingerprint string) {
	t.Helper()
	oldAddr, oldTransport, oldPin := config.SERVER_ADDR, config.SERVER_TRANSPORT, config.SERVER_TLS_FINGERPRINT
	config.SERVER_ADDR, config.SERVER_TRANSPORT, config.SERVER_TLS_FINGERPRINT = addr, transport, fingerprint
	t.Cleanup(func() {
		config.SERVER_ADDR, config.SERVER_TRANSPORT, config.SERVER_TLS_FINGERPRINT = oldAddr, oldTransport, oldPin
	})
}

func TestDialServerTCPDefault(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	withServerConfig(t, listener.Addr().String(), "", "")
	conn, err := dialServer()
	if err != nil {
		t.Fatalf("default TCP dial: %v", err)
	}
	defer conn.Close()
	accepted, err := listener.Accept()
	if err != nil {
		t.Fatal(err)
	}
	accepted.Close()
}

func TestDialServerTLSWithPinnedCertificate(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	defer server.Close()
	addr := strings.TrimPrefix(server.URL, "https://")
	hash := sha256.Sum256(server.Certificate().Raw)
	withServerConfig(t, addr, "tls_tcp", hex.EncodeToString(hash[:]))
	conn, err := dialServer()
	if err != nil {
		t.Fatalf("pinned TLS dial: %v", err)
	}
	if conn == nil {
		t.Fatal("expected TLS connection")
	}
	conn.Close()
}

func TestDialServerTLSRejectsMismatchedPin(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	defer server.Close()
	withServerConfig(t, strings.TrimPrefix(server.URL, "https://"), "tls_tcp", strings.Repeat("0", 64))
	if conn, err := dialServer(); err == nil {
		conn.Close()
		t.Fatal("untrusted server certificate accepted")
	} else if !strings.Contains(err.Error(), "fingerprint mismatch") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestDialServerTLSRejectsMissingOrInvalidPin(t *testing.T) {
	for _, pin := range []string{"", "wrong", strings.Repeat("z", 64)} {
		withServerConfig(t, "127.0.0.1:1", "tls_tcp", pin)
		if conn, err := dialServer(); err == nil {
			conn.Close()
			t.Fatalf("accepted invalid fingerprint %q", pin)
		}
	}
}

func TestDialServerRejectsUnknownTransport(t *testing.T) {
	withServerConfig(t, "127.0.0.1:1", "tls", "")
	if conn, err := dialServer(); err == nil {
		conn.Close()
		t.Fatal("accepted unknown server transport")
	}
}
