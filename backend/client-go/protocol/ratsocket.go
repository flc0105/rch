package protocol

import (
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"sync"
	"time"
)

type RATSocket struct {
	conn   net.Conn
	sendMu sync.Mutex
}

func NewRATSocket(conn net.Conn) *RATSocket {
	return &RATSocket{conn: conn}
}

func (r *RATSocket) Send(data map[string]interface{}) error {
	r.sendMu.Lock()
	defer r.sendMu.Unlock()
	bytes, err := json.Marshal(data)
	if err != nil {
		return err
	}

	header := make([]byte, 4)
	binary.LittleEndian.PutUint32(header, uint32(len(bytes)))

	if _, err := r.conn.Write(header); err != nil {
		return err
	}
	_, err = r.conn.Write(bytes)
	return err
}

func (r *RATSocket) Recv() (map[string]interface{}, error) {
	header := make([]byte, 4)
	if _, err := io.ReadFull(r.conn, header); err != nil {
		return nil, err
	}

	length := binary.LittleEndian.Uint32(header)
	body := make([]byte, length)

	if _, err := io.ReadFull(r.conn, body); err != nil {
		return nil, err
	}

	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, err
	}
	return result, nil
}

func (r *RATSocket) Close() error {
	if r == nil || r.conn == nil {
		return nil
	}
	return r.conn.Close()
}

// Read deadlines are used by the terminating session while awaiting Server ACK.
func (r *RATSocket) SetReadDeadline(deadline time.Time) error {
	return r.conn.SetReadDeadline(deadline)
}
