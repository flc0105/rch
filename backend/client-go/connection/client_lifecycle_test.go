package connection

import (
	"fmt"
	"net"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"client-go/config"
	"client-go/protocol"
)

func TestReverseBackoffCapsAndResetsAfterAdmission(t *testing.T) {
	var retry reverseRetryBackoff
	for i, want := range []time.Duration{5, 10, 20, 30, 30} {
		got := retry.next(5*time.Second, 30*time.Second)
		if got != want*time.Second {
			t.Fatalf("failure %d: got %s, want %ds", i, got, want)
		}
	}
	retry.reset()
	if got := retry.next(5*time.Second, 30*time.Second); got != 5*time.Second {
		t.Fatalf("admitted session must reset to 5s, got %s", got)
	}
}

func testClientSession(t *testing.T, peer func(*protocol.RATSocket)) (bool, error) {
	t.Helper()
	clientConn, serverConn := net.Pipe()
	defer serverConn.Close()
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		server := protocol.NewRATSocket(serverConn)
		if _, err := server.Recv(); err == nil {
			peer(server)
		}
	}()
	client := &Client{clientID: "test-client"}
	accepted, err := client.serveConnectionWithTimeout(clientConn, nil, 65*time.Millisecond)
	<-finished
	return accepted, err
}

func TestSessionIdleTimeoutTriggersReconnectReason(t *testing.T) {
	admitted, err := testClientSession(t, func(sock *protocol.RATSocket) {
		_ = sock.Send(map[string]interface{}{"type": "client_session_token", "token": "session-token"})
		// Wait for the Client to close the idle connection.
		_, _ = sock.Recv()
	})
	if !admitted || err == nil || !strings.Contains(err.Error(), "Server inbound message timeout") {
		t.Fatalf("admitted=%v, error=%v", admitted, err)
	}
}

func TestSessionRejectedKeepsRetryBackoff(t *testing.T) {
	admitted, err := testClientSession(t, func(sock *protocol.RATSocket) {
		_ = sock.Send(map[string]interface{}{"type": "connection_rejected", "message": "Client mTLS identity not authorized or revoked"})
	})
	if admitted || err == nil || !strings.Contains(err.Error(), "Client mTLS identity not authorized or revoked") {
		t.Fatalf("admitted=%v, error=%v", admitted, err)
	}
}

func TestAdmittedSessionReportsRemoteClose(t *testing.T) {
	admitted, err := testClientSession(t, func(sock *protocol.RATSocket) {
		_ = sock.Send(map[string]interface{}{"type": "client_session_token", "token": "session-token"})
		_ = sock.Close()
	})
	if !admitted || err == nil || strings.Contains(err.Error(), "inbound message timeout") {
		t.Fatalf("admitted=%v, error=%v", admitted, err)
	}
}

func TestHandshakeFailureNotAdmitted(t *testing.T) {
	// Server never acknowledges a new session; EOF must not count as a success.
	admitted, err := testClientSession(t, func(sock *protocol.RATSocket) { _ = sock.Close() })
	if admitted || err == nil {
		t.Fatalf("admitted=%v, error=%v", admitted, err)
	}
}

func TestInboundTimeoutResetsAfterEachServerMessage(t *testing.T) {
	admitted, err := testClientSession(t, func(sock *protocol.RATSocket) {
		_ = sock.Send(map[string]interface{}{"type": "client_session_token", "token": "session-token"})
		// The total session lasts longer than one idle period, but no individual
		// gap between inbound frames exceeds the configured timeout.
		for i := 0; i < 4; i++ {
			time.Sleep(20 * time.Millisecond)
			if err := sock.Send(map[string]interface{}{"type": "session_config"}); err != nil {
				break
			}
		}
		_ = sock.Close()
	})
	if !admitted || err == nil || strings.Contains(err.Error(), "inbound message timeout") {
		t.Fatalf("active session was treated as idle: admitted=%v, err=%v", admitted, err)
	}
}

func TestLiveInboundTimeoutConfiguration(t *testing.T) {
	store := config.NewRuntimeStore(filepath.Join(t.TempDir(), "runtime.json"))
	if _, err := store.Set(config.ServerInboundTimeoutConfig, "1"); err != nil {
		t.Fatal(err)
	}
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()
	_ = right.SetDeadline(time.Now().Add(6 * time.Second))
	done := make(chan error, 1)
	go func() {
		client := &Client{clientID: "test-client"}
		admitted, err := client.serveConnectionWithTimeoutSource(left, nil, func() float64 {
			return float64(store.Seconds(config.ServerInboundTimeoutConfig))
		}, 10*time.Millisecond)
		if !admitted {
			done <- fmt.Errorf("session was not admitted: %v", err)
			return
		}
		done <- err
	}()
	peer := protocol.NewRATSocket(right)
	if _, err := peer.Recv(); err != nil {
		t.Fatal(err)
	}
	if err := peer.Send(map[string]interface{}{"type": "client_session_token", "token": "session-token"}); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Set(config.ServerInboundTimeoutConfig, "0"); err != nil {
		t.Fatal(err)
	}
	// Disable the timeout while Recv is already waiting, then remain silent
	// beyond the previous deadline. A heartbeat proves the session is alive.
	time.Sleep(1200 * time.Millisecond)
	if err := peer.Send(map[string]interface{}{"type": "heartbeat", "id": 1}); err != nil {
		t.Fatal(err)
	}
	if msg, err := peer.Recv(); err != nil || msg["type"] != "heartbeat_ack" {
		t.Fatalf("heartbeat: %v %v", msg, err)
	}
	if _, err := store.Set(config.ServerInboundTimeoutConfig, "1"); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-done:
		if err == nil || !strings.Contains(err.Error(), "Server inbound message timeout: no message for 1s") {
			t.Fatalf("unexpected result: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("re-enabled timeout did not interrupt blocked Recv")
	}
}

func TestConfiguredReverseBackoffSequences(t *testing.T) {
	for _, tc := range []struct {
		min, max int
		delays   []int
	}{
		{5, 30, []int{5, 10, 20, 30, 30}},
		{10, 60, []int{10, 20, 40, 60, 60}},
		{20, 30, []int{20, 30, 30}},
		{29, 30, []int{29, 30, 30}},
		{30, 30, []int{30, 30, 30}},
		{60, 60, []int{60, 60, 60}},
	} {
		var retry reverseRetryBackoff
		min, max := time.Duration(tc.min)*time.Second, time.Duration(tc.max)*time.Second
		for _, want := range tc.delays {
			if got := retry.next(min, max); got != time.Duration(want)*time.Second {
				t.Fatalf("%v: got %s want %ds", tc, got, want)
			}
		}
		retry.reset()
		if got := retry.next(min, max); got != min {
			t.Fatalf("reset: %s", got)
		}
	}
}

func TestReverseBackoffUsesLatestBounds(t *testing.T) {
	var retry reverseRetryBackoff
	retry.next(5*time.Second, 30*time.Second)
	if got := retry.next(5*time.Second, 8*time.Second); got != 8*time.Second {
		t.Fatal(got)
	}
	if got := retry.next(25*time.Second, 60*time.Second); got != 25*time.Second {
		t.Fatal(got)
	}
	retry.reset()
	if got := retry.next(60*time.Second, 60*time.Second); got != 60*time.Second {
		t.Fatal(got)
	}
}
