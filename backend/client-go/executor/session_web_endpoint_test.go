package executor

import (
	"strings"
	"testing"

	"client-go/config"
)

func TestSessionWebEndpointBindVsReverse(t *testing.T) {
	old := config.UPLOAD_BASE_URL
	config.UPLOAD_BASE_URL = "http://127.0.0.1:8085"
	t.Cleanup(func() { config.UPLOAD_BASE_URL = old })
	reverse := NewSession(nil, "reverse")
	if reverse.ServerWebBaseURL() != old {
		t.Fatal("Reverse must retain configured Web endpoint")
	}
	bind := NewSession(nil, "bind")
	bind.RequireSessionWebEndpoint()
	if _, err := bind.transferURL("/api/files/upload"); err == nil {
		t.Fatal("Bind should require session_config")
	}
	if err := bind.SetServerWebBaseURL("https://192.168.1.10:8443"); err != nil {
		t.Fatal(err)
	}
	result, err := bind.transferURL("/api/files/upload")
	if err != nil {
		t.Fatal(err)
	}
	if result != "https://192.168.1.10:8443/api/files/upload" {
		t.Fatalf("wrong Bind Web endpoint: %s", result)
	}
	if reverse.ServerWebBaseURL() != old {
		t.Fatal("Bind endpoint leaked into Reverse session")
	}
}

func TestSessionRejectsInvalidWebEndpoint(t *testing.T) {
	s := NewSession(nil, "bind")
	s.RequireSessionWebEndpoint()
	for _, value := range []string{"", "http://", "http://user:pass@server:8085", "http://server:99999", "file:///etc/passwd", "http://server/path", "http://server?token=x", " http://server:8085"} {
		if err := s.SetServerWebBaseURL(value); err == nil {
			t.Fatalf("accepted invalid Web endpoint %q", value)
		}
	}
	if _, err := s.transferURL("http://evil.example/data"); err == nil || !strings.Contains(err.Error(), "invalid") {
		t.Fatalf("unexpected transfer URL result: %v", err)
	}
}
