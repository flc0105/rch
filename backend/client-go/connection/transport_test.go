package connection

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"client-go/config"
)

func withConnectionConfig(t *testing.T, addr, transport, identityDir string) {
	t.Helper()
	oldAddr, oldTransport, oldDir := config.SERVER_ADDR, config.SERVER_TRANSPORT, config.IDENTITY_DIR
	config.SERVER_ADDR, config.SERVER_TRANSPORT, config.IDENTITY_DIR = addr, transport, identityDir
	t.Cleanup(func() {
		config.SERVER_ADDR, config.SERVER_TRANSPORT, config.IDENTITY_DIR = oldAddr, oldTransport, oldDir
	})
}

func TestDialServerTCP(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	withConnectionConfig(t, listener.Addr().String(), "tcp", "")
	conn, err := dialServer()
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	peer, err := listener.Accept()
	if err != nil {
		t.Fatal(err)
	}
	peer.Close()
}

// Build test PEMs in the same three-file layout as the Python Identity download.
func signedCertificate(t *testing.T, ca *x509.Certificate, caKey *rsa.PrivateKey, role string) (tls.Certificate, *x509.Certificate, []byte) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()),
		Subject:      pkix.Name{CommonName: "RCH " + role},
		NotBefore:    time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		KeyUsage:    x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth, x509.ExtKeyUsageClientAuth},
	}
	if ca == nil {
		tmpl.IsCA = true
		tmpl.BasicConstraintsValid = true
		tmpl.KeyUsage = x509.KeyUsageCertSign | x509.KeyUsageCRLSign
		ca = tmpl
		caKey = key
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, ca, &key.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	result, err := tls.X509KeyPair(certPEM, keyPEM)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return result, parsed, certPEM
}

func provisionPEM(t *testing.T) (dir string, serverCert tls.Certificate, clientCert tls.Certificate, serverRoot *x509.CertPool, clientRoot *x509.CertPool) {
	t.Helper()
	serverCAKey, _ := rsa.GenerateKey(rand.Reader, 2048)
	serverCATemplate := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "RCH Server trust root"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign}
	serverDER, err := x509.CreateCertificate(rand.Reader, serverCATemplate, serverCATemplate, &serverCAKey.PublicKey, serverCAKey)
	if err != nil {
		t.Fatal(err)
	}
	serverCA, _ := x509.ParseCertificate(serverDER)
	clientCAKey, _ := rsa.GenerateKey(rand.Reader, 2048)
	clientCATemplate := &x509.Certificate{SerialNumber: big.NewInt(2), Subject: pkix.Name{CommonName: "RCH Client trust root"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign}
	clientDER, err := x509.CreateCertificate(rand.Reader, clientCATemplate, clientCATemplate, &clientCAKey.PublicKey, clientCAKey)
	if err != nil {
		t.Fatal(err)
	}
	clientCA, _ := x509.ParseCertificate(clientDER)
	serverCert, _, _ = signedCertificate(t, serverCA, serverCAKey, "Server")
	clientCert, _, clientPEM := signedCertificate(t, clientCA, clientCAKey, "Client")
	dir = t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "client.crt"), clientPEM, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "client.key"), pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(clientCert.PrivateKey.(*rsa.PrivateKey))}), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "server-ca.crt"), pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: serverDER}), 0600); err != nil {
		t.Fatal(err)
	}
	serverRoot = x509.NewCertPool()
	serverRoot.AddCert(serverCA)
	clientRoot = x509.NewCertPool()
	clientRoot.AddCert(clientCA)
	return
}

func TestReverseMutualTLSFromPythonIdentityLayout(t *testing.T) {
	dir, serverCert, _, _, clientCA := provisionPEM(t)
	listener, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{
		Certificates: []tls.Certificate{serverCert}, ClientAuth: tls.RequireAndVerifyClientCert,
		ClientCAs: clientCA, MinVersion: tls.VersionTLS12,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	status := make(chan error, 1)
	go func() {
		peer, err := listener.Accept()
		if err != nil {
			status <- err
			return
		}
		defer peer.Close()
		status <- peer.(*tls.Conn).Handshake()
	}()
	withConnectionConfig(t, listener.Addr().String(), "mtls_tcp", dir)
	conn, err := dialServer()
	if err != nil {
		t.Fatalf("reverse mTLS handshake: %v", err)
	}
	defer conn.Close()
	if err := <-status; err != nil {
		t.Fatalf("server rejects Client identity: %v", err)
	}
	if _, ok := conn.(*tls.Conn); !ok {
		t.Fatal("expected TLS connection")
	}
	if _, err := conn.Write([]byte("session data")); err != nil {
		t.Fatal(err)
	}
}

func TestBindMutualTLSWithServerRoleCertificate(t *testing.T) {
	dir, serverCert, _, serverCA, clientCA := provisionPEM(t)
	withConnectionConfig(t, "", "mtls_tcp", dir)
	oldHost, oldPort := config.BIND_HOST, config.BIND_PORT
	config.BIND_HOST = "127.0.0.1"
	free, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	config.BIND_PORT = free.Addr().(*net.TCPAddr).Port
	free.Close()
	t.Cleanup(func() { config.BIND_HOST, config.BIND_PORT = oldHost, oldPort })
	listener, err := listenBind()
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	status := make(chan error, 1)
	go func() {
		peer, e := acceptBind(listener)
		if e == nil {
			defer peer.Close()
			_, e = peer.Write([]byte("ok"))
		}
		status <- e
	}()
	conn, err := tls.Dial("tcp", listener.Addr().String(), &tls.Config{
		Certificates: []tls.Certificate{serverCert}, RootCAs: clientCA,
		InsecureSkipVerify: true,
		VerifyConnection: func(state tls.ConnectionState) error {
			_, err := state.PeerCertificates[0].Verify(x509.VerifyOptions{Roots: clientCA, KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}})
			return err
		}, MinVersion: tls.VersionTLS12,
	})
	_ = serverCA
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	buf := make([]byte, 2)
	if _, err = conn.Read(buf); err != nil {
		t.Fatal(err)
	}
	if err = <-status; err != nil {
		t.Fatal(err)
	}
}

func TestMutualTLSRejectsUntrustedServer(t *testing.T) {
	dir, _, _, _, clientCA := provisionPEM(t)
	otherDir, otherServer, _, _, _ := provisionPEM(t)
	_ = otherDir
	listener, err := tls.Listen("tcp", "127.0.0.1:0", &tls.Config{Certificates: []tls.Certificate{otherServer}, ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: clientCA})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	go func() {
		conn, e := listener.Accept()
		if e == nil {
			defer conn.Close()
			_ = conn.(*tls.Conn).Handshake()
		}
	}()
	withConnectionConfig(t, listener.Addr().String(), "mtls_tcp", dir)
	if conn, err := dialServer(); err == nil {
		conn.Close()
		t.Fatal("untrusted Server certificate accepted")
	} else if !strings.Contains(err.Error(), "Server mTLS identity not trusted") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestMissingIdentityAndUnsupportedTransport(t *testing.T) {
	withConnectionConfig(t, "127.0.0.1:1", "mtls_tcp", t.TempDir())
	if _, err := dialServer(); err == nil || !strings.Contains(err.Error(), "identity file missing") {
		t.Fatalf("unexpected error: %v", err)
	}
	config.SERVER_TRANSPORT = "tls_tcp"
	if _, err := dialServer(); err == nil || !strings.Contains(err.Error(), "unsupported server transport") {
		t.Fatalf("unsupported old TLS: %v", err)
	}
}

func TestBindTCPDoesNotLoadIdentity(t *testing.T) {
	withConnectionConfig(t, "", "tcp", filepath.Join(t.TempDir(), "missing-identity"))
	oldHost, oldPort := config.BIND_HOST, config.BIND_PORT
	config.BIND_HOST = "127.0.0.1"
	free, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	config.BIND_PORT = free.Addr().(*net.TCPAddr).Port
	free.Close()
	t.Cleanup(func() { config.BIND_HOST, config.BIND_PORT = oldHost, oldPort })
	listener, err := listenBind()
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	peer, err := net.DialTimeout("tcp", listener.Addr().String(), time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	accepted, err := acceptBind(listener)
	if err != nil {
		t.Fatal(err)
	}
	accepted.Close()
}
