package connection

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"sync"
	"time"

	"client-go/config"
	"client-go/executor"
	"client-go/handler"
	"client-go/protocol"
)

type Client struct {
	clientID string
	identity hostIdentity
	launch   launchContext
}

func New() *Client {
	return &Client{clientID: executor.NewClientID(), identity: detectHostIdentity(), launch: detectLaunchContext()}
}

func (c *Client) Run() {
	switch config.CONNECTION_MODE {
	case "reverse":
		c.runReverse()
	case "bind":
		c.runBind()
	default:
		log.Printf("unsupported connection mode: %s", config.CONNECTION_MODE)
	}
}

// Reverse retries are reset only after the Server admits a session.
type reverseRetryBackoff struct{ previousDelay time.Duration }

func (r *reverseRetryBackoff) reset() { r.previousDelay = 0 }
func (r *reverseRetryBackoff) next(minimum, maximum time.Duration) time.Duration {
	// Read the current bounds at each retry; clamp before doubling to avoid overflow.
	delay := maximum
	if r.previousDelay <= maximum/2 {
		delay = r.previousDelay * 2
	}
	if delay < minimum {
		delay = minimum
	}
	r.previousDelay = delay
	return delay
}

func (c *Client) runReverse() {
	var retry reverseRetryBackoff
	for {
		conn, err := dialServer()
		admitted := false
		if err == nil {
			admitted, err = c.serveConnection(conn, nil)
			if admitted {
				retry.reset()
			}
		}
		if err == nil {
			err = io.EOF
		}
		if admitted {
			log.Printf("RCH connection lost: %v", err)
		} else {
			log.Printf("RCH connection failed: %v", err)
		}
		minimum, maximum := config.Runtime().ReconnectBackoffBounds()
		delay := retry.next(time.Duration(minimum)*time.Second, time.Duration(maximum)*time.Second)
		log.Printf("Reconnecting in %gs after: %v", delay.Seconds(), err)
		time.Sleep(delay)
	}
}

func (c *Client) runBind() {
	listener, err := listenBind()
	if err != nil {
		log.Printf("RCH Bind listener failed: %v", err)
		return
	}
	defer listener.Close()
	log.Printf("RCH Bind listening on %s (%s)", listener.Addr(), config.SERVER_TRANSPORT)
	var mu sync.Mutex
	var active *bindFileRouter
	for {
		conn, err := acceptBind(listener)
		if err != nil {
			log.Printf("RCH Bind acceptance failed: %v", err)
			continue
		}
		mu.Lock()
		current := active
		if current == nil {
			current = newBindFileRouter()
			active = current
			mu.Unlock()
			go func(router *bindFileRouter, primary net.Conn) {
				_, reason := c.serveConnection(primary, router)
				log.Printf("RCH Bind connection lost: %v", reason)
				router.close()
				mu.Lock()
				if active == router {
					active = nil
				}
				mu.Unlock()
			}(current, conn)
		} else {
			mu.Unlock()
			go current.dispatch(conn)
		}
	}
}

func (c *Client) serveConnection(conn net.Conn, router *bindFileRouter) (bool, error) {
	return c.serveConnectionWithTimeoutSource(conn, router, func() float64 {
		return float64(config.Runtime().Seconds(config.ServerInboundTimeoutConfig))
	}, 500*time.Millisecond)
}

func (c *Client) serveConnectionWithTimeout(conn net.Conn, router *bindFileRouter, timeout time.Duration) (bool, error) {
	return c.serveConnectionWithTimeoutSource(conn, router, func() float64 { return timeout.Seconds() }, 5*time.Millisecond)
}

func (c *Client) serveConnectionWithTimeoutSource(conn net.Conn, router *bindFileRouter, timeoutSeconds func() float64, checkInterval time.Duration) (bool, error) {
	sock := protocol.NewRATSocket(conn)
	session := executor.NewSession(sock, c.clientID)
	defer session.Close()
	if router != nil {
		session.RequireSessionWebEndpoint()
		session.SetFileDataOpener(router.expect)
	} else {
		session.SetFileDataOpener(func(ctx context.Context, id, token string, _ func()) (net.Conn, error) {
			data, err := dialServer()
			if err != nil {
				return nil, err
			}
			if err = executor.SendFileDataGreeting(data, id, token); err != nil {
				data.Close()
				return nil, err
			}
			return data, nil
		})
	}
	if err := sock.Send(c.buildHandshake(session.CurrentDirectory())); err != nil {
		return false, fmt.Errorf("RCH handshake failed: %w", err)
	}
	idle := startInboundIdleMonitor(sock, timeoutSeconds, checkInterval)
	defer idle.stop()
	admitted := false
	for {
		msg, err := sock.Recv()
		if err != nil {
			if reason := idle.reason(); reason != nil {
				return admitted, reason
			}
			return admitted, err
		}
		idle.received()
		switch msg["type"] {
		case "client_session_token":
			token, _ := msg["token"].(string)
			if token == "" {
				return admitted, errors.New("Server sent an empty Client Session Token")
			}
			session.SetSessionToken(token)
			admitted = true
			continue
		case "connection_rejected":
			return admitted, fmt.Errorf("RCH connection rejected: %v", msg["message"])
		case "session_config":
			if config.CONNECTION_MODE == "bind" {
				endpoint, ok := msg["server_web_base_url"].(string)
				if !ok {
					return admitted, errors.New("Invalid Bind Server Web URL")
				}
				if err := session.SetServerWebBaseURL(endpoint); err != nil {
					return admitted, fmt.Errorf("RCH session config failed: %w", err)
				}
			}
			continue
		}
		handler.Handle(session, msg)
	}
}
