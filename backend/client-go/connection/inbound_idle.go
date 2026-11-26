package connection

import (
	"fmt"
	"sync"
	"time"

	"client-go/protocol"
)

// Check the current configuration while Recv is blocked, including a change
// to or from zero. Only complete inbound messages refresh the idle clock.
type inboundIdleMonitor struct {
	mu       sync.Mutex
	last     time.Time
	failure  error
	done     chan struct{}
	finished chan struct{}
}

func startInboundIdleMonitor(sock *protocol.RATSocket, timeoutSeconds func() float64, interval time.Duration) *inboundIdleMonitor {
	m := &inboundIdleMonitor{last: time.Now(), done: make(chan struct{}), finished: make(chan struct{})}
	go func() {
		defer close(m.finished)
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-m.done:
				return
			case <-ticker.C:
				m.mu.Lock()
				timeout := timeoutSeconds()
				if timeout > 0 && time.Since(m.last).Seconds() >= timeout {
					m.failure = fmt.Errorf("Server inbound message timeout: no message for %gs", timeout)
					m.mu.Unlock()
					_ = sock.Close()
					return
				}
				m.mu.Unlock()
			}
		}
	}()
	return m
}

func (m *inboundIdleMonitor) received() {
	m.mu.Lock()
	m.last = time.Now()
	m.mu.Unlock()
}

func (m *inboundIdleMonitor) reason() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.failure
}

func (m *inboundIdleMonitor) stop() {
	close(m.done)
	<-m.finished
}
