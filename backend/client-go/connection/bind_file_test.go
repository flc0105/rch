package connection

import (
	"context"
	"net"
	"testing"
	"time"

	"client-go/executor"
)

func TestBindAuxiliaryRoutesOnlyMatchingSessionToken(t *testing.T) {
	router := newBindFileRouter()
	defer router.close()
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	type result struct {
		conn net.Conn
		err  error
	}
	pending := make(chan result, 1)
	go func() {
		conn, err := router.expect(ctx, "transfer-a", "token-a", func() {})
		pending <- result{conn, err}
	}()
	time.Sleep(20 * time.Millisecond)
	wrong, other := net.Pipe()
	go router.dispatch(other)
	if err := executor.SendFileDataGreeting(wrong, "transfer-a", "wrong-token"); err != nil {
		t.Fatal(err)
	}
	wrong.Close()
	correct, aux := net.Pipe()
	go router.dispatch(aux)
	if err := executor.SendFileDataGreeting(correct, "transfer-a", "token-a"); err != nil {
		t.Fatal(err)
	}
	defer correct.Close()
	select {
	case got := <-pending:
		if got.err != nil || got.conn == nil {
			t.Fatalf("valid auxiliary rejected: %v", got.err)
		}
		got.conn.Close()
	case <-time.After(2 * time.Second):
		t.Fatal("Bind auxiliary not routed")
	}
}

func TestBindAuxiliaryShutdownUnblocksWaitingTransfer(t *testing.T) {
	router := newBindFileRouter()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	done := make(chan error, 1)
	go func() { _, err := router.expect(ctx, "x", "token", func() {}); done <- err }()
	time.Sleep(20 * time.Millisecond)
	router.close()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("closed router accepted transfer")
		}
	case <-time.After(time.Second):
		t.Fatal("pending transfer not released")
	}
}
