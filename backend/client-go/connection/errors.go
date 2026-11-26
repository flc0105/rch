package connection

import (
	"errors"
	"fmt"
	"net"
)

type terminalConnectionError struct {
	category string
	cause    error
}

func (e *terminalConnectionError) Error() string { return fmt.Sprintf("%s: %v", e.category, e.cause) }
func (e *terminalConnectionError) Unwrap() error { return e.cause }

func configurationFailure(err error) error {
	return &terminalConnectionError{"Connection configuration failed", err}
}

func authenticationFailure(err error) error {
	return &terminalConnectionError{"Connection authentication rejected", err}
}

func terminalFailure(err error, mtls bool) error {
	var terminal *terminalConnectionError
	if errors.As(err, &terminal) {
		return terminal
	}
	// crypto/tls returns explicit peer alerts as net.OpError with this Op.
	// Do not infer certificate failure from arbitrary error text. EOF, socket
	// resets and timeouts are not explicit TLS refusals.
	var op *net.OpError
	if mtls && errors.As(err, &op) && op.Op == "remote error" {
		return &terminalConnectionError{"mTLS peer rejected connection", err}
	}
	return nil
}
