package connection

import (
	"crypto/sha256"
	"crypto/subtle"
	"crypto/tls"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"strings"
	"time"

	"client-go/config"
)

// dialServer selects the listener transport provisioned by Agent Builder.
// TLS is pinned to the Server listener certificate, like the Python client.
func dialServer() (net.Conn, error) {
	switch config.SERVER_TRANSPORT {
	case "", "tcp":
		return net.Dial("tcp", config.SERVER_ADDR)
	case "tls_tcp":
		expected, err := hex.DecodeString(strings.ToLower(strings.TrimSpace(config.SERVER_TLS_FINGERPRINT)))
		if err != nil || len(expected) != sha256.Size {
			return nil, errors.New("invalid TLS server certificate fingerprint")
		}
		tlsConfig := &tls.Config{
			MinVersion: tls.VersionTLS12,
			// The listener uses a self-signed certificate; its SHA-256 fingerprint
			// is verified before any RCH protocol data is sent.
			InsecureSkipVerify: true,
			VerifyConnection: func(state tls.ConnectionState) error {
				if len(state.PeerCertificates) == 0 {
					return errors.New("TLS server did not present a certificate")
				}
				actual := sha256.Sum256(state.PeerCertificates[0].Raw)
				if subtle.ConstantTimeCompare(actual[:], expected) != 1 {
					return errors.New("TLS server certificate fingerprint mismatch")
				}
				return nil
			},
		}
		dialer := &net.Dialer{Timeout: 10 * time.Second}
		return tls.DialWithDialer(dialer, "tcp", config.SERVER_ADDR, tlsConfig)
	default:
		return nil, fmt.Errorf("unsupported server transport: %s", config.SERVER_TRANSPORT)
	}
}
