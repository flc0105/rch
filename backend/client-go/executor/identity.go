package executor

import (
	"crypto/rand"
	"fmt"
	"io"
)

func NewClientID() string {
	buf := make([]byte, 16)
	if _, err := io.ReadFull(rand.Reader, buf); err != nil {
		return fallbackClientID()
	}

	buf[6] = (buf[6] & 0x0f) | 0x40
	buf[8] = (buf[8] & 0x3f) | 0x80

	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		bytesToUint32(buf[0:4]),
		bytesToUint16(buf[4:6]),
		bytesToUint16(buf[6:8]),
		bytesToUint16(buf[8:10]),
		bytesToUint48(buf[10:16]),
	)
}

func DetectHandshakeIntegrity() string {
	return detectIntegrity()
}

func fallbackClientID() string {
	return fmt.Sprintf("fallback-%s", detectMachineToken())
}

func bytesToUint16(b []byte) uint16 {
	var v uint16
	for _, x := range b {
		v = (v << 8) | uint16(x)
	}
	return v
}

func bytesToUint32(b []byte) uint32 {
	var v uint32
	for _, x := range b {
		v = (v << 8) | uint32(x)
	}
	return v
}

func bytesToUint48(b []byte) uint64 {
	var v uint64
	for _, x := range b {
		v = (v << 8) | uint64(x)
	}
	return v
}
