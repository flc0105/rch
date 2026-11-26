package connection

import (
	"crypto/tls"
	"errors"
	"io"
	"net"
	"os"
	"strings"
	"testing"
	"time"

	"client-go/config"
)

func TestNetworkErrorsRemainDistinct(t *testing.T) {
	for _, err := range []error{io.EOF, os.ErrDeadlineExceeded, &net.OpError{Op: "read", Err: errors.New("reset")}} {
		if terminalFailure(err, true) != nil {
			t.Fatalf("network error misclassified: %v", err)
		}
	}
}

func TestReverseMissingIdentityStops(t *testing.T) {
	withConnectionConfig(t, "127.0.0.1:1", "mtls_tcp", t.TempDir())
	c := &Client{}
	err := c.runReverse()
	if terminalFailure(err, true) == nil || !strings.Contains(err.Error(), "identity file missing") {
		t.Fatalf("unexpected terminal result: %v", err)
	}
}

func TestReverseInvalidAddressStops(t *testing.T) {
	withConnectionConfig(t, "127.0.0.1:0", "tcp", "")
	err := (&Client{}).runReverse()
	if terminalFailure(err, false) == nil {
		t.Fatalf("unexpected result: %v", err)
	}
}

func TestBindOccupiedPortStops(t *testing.T) {
	occupied, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer occupied.Close()
	withConnectionConfig(t, "", "tcp", "")
	oldHost, oldPort := config.BIND_HOST, config.BIND_PORT
	config.BIND_HOST, config.BIND_PORT = "127.0.0.1", occupied.Addr().(*net.TCPAddr).Port
	t.Cleanup(func() { config.BIND_HOST, config.BIND_PORT = oldHost, oldPort })
	err = (&Client{}).runBind()
	if terminalFailure(err, false) == nil || !strings.Contains(err.Error(), "Bind listener startup failed") {
		t.Fatalf("unexpected terminal result: %v", err)
	}
}

// A TLS peer explicitly refusing a certificate is different from TCP EOF.
func TestActualPeerTLSRejectionIsTerminal(t *testing.T) {
	dir, serverCert, _, serverCA, _ := provisionPEM(t)
	for _, version := range []uint16{tls.VersionTLS12, tls.VersionTLS13} {
		listener, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{
			Certificates: []tls.Certificate{serverCert}, ClientAuth: tls.RequireAndVerifyClientCert,
			ClientCAs: serverCA, MinVersion: version, MaxVersion: version,
		})
		if err != nil {
			t.Fatal(err)
		}
		done := make(chan error, 1)
		go func() {
			conn, err := listener.Accept()
			if err != nil {
				done <- err
				return
			}
			defer conn.Close()
			_ = conn.SetDeadline(time.Now().Add(2 * time.Second))
			done <- conn.(*tls.Conn).Handshake()
		}()
		withConnectionConfig(t, listener.Addr().String(), "mtls_tcp", dir)
		conn, err := dialServer()
		if err == nil {
			_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
			_, err = conn.Read(make([]byte, 1))
			conn.Close()
		}
		listener.Close()
		if serverErr := <-done; serverErr == nil {
			t.Fatal("untrusted Client accepted")
		}
		if terminalFailure(err, true) == nil {
			t.Fatalf("TLS version %x: rejection was not terminal: %T %v", version, err, err)
		}
	}
}
