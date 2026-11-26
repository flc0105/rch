package connection

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"client-go/config"
)

const handshakeTimeout = 5 * time.Second

// identityPath matches the persistent Python Client identity directory.
func identityPath() (string, error) {
	if config.IDENTITY_DIR != "" {
		if !filepath.IsAbs(config.IDENTITY_DIR) {
			return "", errors.New("mTLS identity_dir must be an absolute path")
		}
		return config.IDENTITY_DIR, nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, "client_bundle", "identity"), nil
}

// identityTLSConfig trusts Server certificates through server-ca.crt only.
// Python's app-local Server certificates contain a CN but no DNS SAN, so
// authorization verifies the chain and ServerAuth EKU without hostname matching.
func identityTLSConfig(forBind bool) (*tls.Config, error) {
	root, err := identityPath()
	if err != nil {
		return nil, err
	}
	crt := filepath.Join(root, "client.crt")
	key := filepath.Join(root, "client.key")
	ca := filepath.Join(root, "server-ca.crt")
	for _, path := range []string{crt, key, ca} {
		if _, err := os.Stat(path); err != nil {
			return nil, fmt.Errorf("mTLS identity file missing: %s: %w", path, err)
		}
	}
	if runtime.GOOS != "windows" {
		info, err := os.Stat(key)
		if err != nil {
			return nil, err
		}
		if info.Mode().Perm()&0077 != 0 {
			return nil, errors.New("mTLS private key must not be accessible by group or others")
		}
	}
	clientCert, err := tls.LoadX509KeyPair(crt, key)
	if err != nil {
		return nil, fmt.Errorf("load Client mTLS identity: %w", err)
	}
	caBytes, err := os.ReadFile(ca)
	if err != nil {
		return nil, err
	}
	trust := x509.NewCertPool()
	if !trust.AppendCertsFromPEM(caBytes) {
		return nil, errors.New("invalid Server trust root")
	}
	verifyServer := func(state tls.ConnectionState) error {
		if len(state.PeerCertificates) == 0 {
			return authenticationFailure(errors.New("Server mTLS certificate missing"))
		}
		intermediates := x509.NewCertPool()
		for _, cert := range state.PeerCertificates[1:] {
			intermediates.AddCert(cert)
		}
		_, err := state.PeerCertificates[0].Verify(x509.VerifyOptions{
			Roots: trust, Intermediates: intermediates,
			KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		})
		if err != nil {
			return authenticationFailure(fmt.Errorf("Server mTLS identity not trusted: %w", err))
		}
		return nil
	}
	tlsConfig := &tls.Config{
		MinVersion:       tls.VersionTLS12,
		Certificates:     []tls.Certificate{clientCert},
		VerifyConnection: verifyServer,
	}
	if forBind {
		// The Server dials in Bind, but still presents the Server-role identity.
		tlsConfig.ClientAuth = tls.RequireAnyClientCert
	} else {
		// Python intentionally verifies the Server CA rather than its IP or DNS name.
		// Go requires explicit certificate verification when hostname checks are disabled.
		tlsConfig.InsecureSkipVerify = true
	}
	return tlsConfig, nil
}

func dialServer() (net.Conn, error) {
	host, port, err := net.SplitHostPort(config.SERVER_ADDR)
	n, portErr := strconv.Atoi(port)
	if err != nil || strings.TrimSpace(host) == "" || portErr != nil || n < 1 || n > 65535 {
		return nil, configurationFailure(errors.New("invalid Reverse server host or port"))
	}
	switch config.SERVER_TRANSPORT {
	case "tcp":
		return net.DialTimeout("tcp", config.SERVER_ADDR, 10*time.Second)
	case "mtls_tcp":
		tlsConfig, err := identityTLSConfig(false)
		if err != nil {
			return nil, configurationFailure(err)
		}
		raw, err := net.DialTimeout("tcp", config.SERVER_ADDR, 10*time.Second)
		if err != nil {
			return nil, err
		}
		secure := tls.Client(raw, tlsConfig)
		_ = secure.SetDeadline(time.Now().Add(handshakeTimeout))
		if err = secure.Handshake(); err != nil {
			secure.Close()
			return nil, err
		}
		if err = secure.SetDeadline(time.Time{}); err != nil {
			secure.Close()
			return nil, err
		}
		return secure, nil
	default:
		return nil, configurationFailure(fmt.Errorf("unsupported server transport: %s", config.SERVER_TRANSPORT))
	}
}

func listenBind() (net.Listener, error) {
	if strings.TrimSpace(config.BIND_HOST) == "" {
		return nil, errors.New("invalid Bind listen host")
	}
	addr := net.JoinHostPort(config.BIND_HOST, fmt.Sprint(config.BIND_PORT))
	if config.BIND_PORT < 1 || config.BIND_PORT > 65535 {
		return nil, errors.New("invalid Bind listen port")
	}
	switch config.SERVER_TRANSPORT {
	case "tcp":
		return net.Listen("tcp", addr)
	case "mtls_tcp":
		tlsConfig, err := identityTLSConfig(true)
		if err != nil {
			return nil, err
		}
		listener, err := net.Listen("tcp", addr)
		if err != nil {
			return nil, err
		}
		return tls.NewListener(listener, tlsConfig), nil
	default:
		return nil, fmt.Errorf("unsupported server transport: %s", config.SERVER_TRANSPORT)
	}
}

func acceptBind(listener net.Listener) (net.Conn, error) {
	conn, err := listener.Accept()
	if err != nil {
		return nil, err
	}
	if secure, ok := conn.(*tls.Conn); ok {
		_ = secure.SetDeadline(time.Now().Add(handshakeTimeout))
		if err = secure.Handshake(); err != nil {
			secure.Close()
			return nil, err
		}
		if err = secure.SetDeadline(time.Time{}); err != nil {
			secure.Close()
			return nil, err
		}
	}
	return conn, nil
}
