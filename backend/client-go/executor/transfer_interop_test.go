package executor

import (
	"bytes"
	"context"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestPythonFileStreamInterop(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("python3 is unavailable")
	}
	backend, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	input := bytes.Repeat([]byte("interop\x00\xf0\x9f\x8c\x8d"), 4096)
	root := t.TempDir()
	source := filepath.Join(root, "源文件.bin")
	output := filepath.Join(root, "from-python.bin")
	if err := os.WriteFile(source, input, 0600); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	script := `import socket,sys
from core.protocol.auxiliary import receive_greeting
from core.protocol.file_stream import receive_control, receive_file, send_control,send_file
from pathlib import Path
s=socket.create_connection(("127.0.0.1",int(sys.argv[1])))
assert receive_greeting(s)=={'type':'transfer_data','transfer_id':'test','token':'token'}
send_control(s,{'ok':True})
h=receive_control(s)
receive_file(s,sys.argv[2],h)
send_control(s,{'ok':True,'data':{'artifact_id':'py-test'}})
send_file(s,sys.argv[2],metadata={})
assert receive_control(s)=={'ok':True,'size':Path(sys.argv[2]).stat().st_size}
s.close()
`
	cmd := exec.Command(python, "-c", script, fmt.Sprint(listener.Addr().(*net.TCPAddr).Port), output)
	cmd.Env = append(os.Environ(), "PYTHONPATH="+backend)
	finished := make(chan error, 1)
	go func() { finished <- cmd.Run() }()
	sock, err := listener.Accept()
	if err != nil {
		t.Fatal(err)
	}
	defer sock.Close()
	if err = SendFileDataGreeting(sock, "test", "token"); err != nil {
		t.Fatal(err)
	}
	if ack, err := receiveFileControl(sock); err != nil || ack["ok"] != true {
		t.Fatalf("greeting ack: %v %v", ack, err)
	}
	if _, err = sendTCPFile(context.Background(), sock, source, map[string]interface{}{"filename": "源文件.bin"}, nil); err != nil {
		t.Fatal(err)
	}
	if ack, err := receiveFileControl(sock); err != nil || ack["ok"] != true {
		t.Fatalf("upload ack: %v %v", ack, err)
	}
	header, err := receiveFileControl(sock)
	if err != nil {
		t.Fatal(err)
	}
	staged, err := os.CreateTemp(root, "received-")
	if err != nil {
		t.Fatal(err)
	}
	defer staged.Close()
	size, err := receiveTCPFile(context.Background(), sock, staged, header, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err = writeFileControl(sock, map[string]interface{}{"ok": true, "size": size}); err != nil {
		t.Fatal(err)
	}
	if err = <-finished; err != nil {
		t.Fatalf("python interop: %v", err)
	}
	bytesOut, err := os.ReadFile(staged.Name())
	if err != nil || !bytes.Equal(bytesOut, input) {
		t.Fatalf("cross-language mismatch: %v", err)
	}
}
