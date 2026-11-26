package connection

import (
	"context"
	"errors"
	"net"
	"sync"
	"time"

	"client-go/executor"
)

// Bind keeps one primary session but accepts matched data sockets on the same
// TCP/mTLS listener. Data sockets never become a second primary session.
type bindFileSlot struct {
	token string
	conn  chan net.Conn
}

type bindFileRouter struct {
	mu      sync.Mutex
	slots   map[string]bindFileSlot
	stopped chan struct{}
	closed  bool
}

func newBindFileRouter() *bindFileRouter {
	return &bindFileRouter{slots: make(map[string]bindFileSlot), stopped: make(chan struct{})}
}

func (r *bindFileRouter) expect(ctx context.Context, id, token string, ready func()) (net.Conn, error) {
	slot := bindFileSlot{token: token, conn: make(chan net.Conn, 1)}
	r.mu.Lock()
	if r.closed {
		r.mu.Unlock()
		return nil, errors.New("Bind session closed")
	}
	if _, ok := r.slots[id]; ok {
		r.mu.Unlock()
		return nil, errors.New("duplicate file data connection")
	}
	if len(r.slots) >= 32 {
		r.mu.Unlock()
		return nil, errors.New("too many pending file connections")
	}
	r.slots[id] = slot
	r.mu.Unlock()
	defer func() {
		r.mu.Lock()
		delete(r.slots, id)
		r.mu.Unlock()
		// A late auxiliary arrival after cancellation is never retained.
		select {
		case unused := <-slot.conn:
			_ = unused.Close()
		default:
		}
	}()
	ready() // Server starts its Bind data dial in response.
	timer := time.NewTimer(15 * time.Second)
	defer timer.Stop()
	select {
	case conn := <-slot.conn:
		if err := ctx.Err(); err != nil {
			conn.Close()
			return nil, err
		}
		return conn, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-r.stopped:
		return nil, errors.New("Bind session closed")
	case <-timer.C:
		return nil, errors.New("timed out waiting for Bind file data connection")
	}
}

func (r *bindFileRouter) dispatch(conn net.Conn) {
	defer func() {
		if conn != nil {
			_ = conn.Close()
		}
	}()
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	id, token, err := executor.ReadFileDataGreeting(conn)
	if err != nil {
		return
	}
	_ = conn.SetReadDeadline(time.Time{})
	r.mu.Lock()
	slot, found := r.slots[id]
	if found && slot.token == token {
		select {
		case slot.conn <- conn:
			conn = nil
		default:
		}
	}
	r.mu.Unlock()
}

func (r *bindFileRouter) close() {
	r.mu.Lock()
	if !r.closed {
		r.closed = true
		close(r.stopped)
	}
	r.mu.Unlock()
}
