package executor

import (
	"context"
	"net"
	"sync"
	"testing"
	"time"

	"client-go/protocol"
)

func TestManagedTransfersCancelAndFinishBeforeSessionShutdown(t *testing.T) {
	var transfers transferTracker
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if !transfers.start("first", cancel) {
		t.Fatal("could not register managed transfer")
	}
	workerFinished := make(chan struct{})
	go func() {
		defer close(workerFinished)
		defer transfers.finish("first")
		<-ctx.Done()
	}()
	closed := make(chan struct{})
	go func() { transfers.close(); close(closed) }()
	select {
	case <-closed:
	case <-time.After(time.Second):
		t.Fatal("session shutdown did not cancel the managed transfer")
	}
	select {
	case <-workerFinished:
	default:
		t.Fatal("transfer worker still active after session shutdown")
	}
	if transfers.start("late", func() {}) {
		t.Fatal("closed session accepted a new managed transfer")
	}
	transfers.close() // repeated shutdown stays safe
}

func TestManagedTransferTrackerCancelsBothTransferModesAtSessionBoundary(t *testing.T) {
	// Transfer lifecycle belongs to the Session, not an HTTP or TCP strategy.
	left, right := net.Pipe()
	defer left.Close()
	defer right.Close()
	session := NewSession(protocol.NewRATSocket(left), "client")
	var ready sync.WaitGroup
	for _, id := range []string{"http_streaming", "tcp_streaming"} {
		ctx, cancel := context.WithCancel(context.Background())
		if !session.transfers.start(id, cancel) {
			t.Fatalf("unable to track %s", id)
		}
		ready.Add(1)
		go func(id string, ctx context.Context) {
			defer session.transfers.finish(id)
			ready.Done()
			<-ctx.Done()
		}(id, ctx)
	}
	ready.Wait()
	shutdown := make(chan struct{})
	go func() { session.CloseTransfers(); close(shutdown) }()
	select {
	case <-shutdown:
	case <-time.After(time.Second):
		t.Fatal("file strategies did not stop with session")
	}
}
