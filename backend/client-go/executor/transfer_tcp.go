package executor

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"time"

	"client-go/config"
)

const maxFileControl = 1024 * 1024
const maxFileGreeting = 4096
const fileIOTimeout = 120 * time.Second

func writeFileControl(conn net.Conn, packet map[string]interface{}) error {
	body, err := json.Marshal(packet)
	if err != nil {
		return err
	}
	if len(body) == 0 || len(body) > maxFileControl {
		return errors.New("invalid file control frame size")
	}
	var header [4]byte
	binary.BigEndian.PutUint32(header[:], uint32(len(body)))
	if err = writeFileBytes(conn, header[:]); err != nil {
		return err
	}
	return writeFileBytes(conn, body)
}

func writeFileBytes(conn net.Conn, data []byte) error {
	for len(data) > 0 {
		if err := conn.SetWriteDeadline(time.Now().Add(fileIOTimeout)); err != nil {
			return err
		}
		n, err := conn.Write(data)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		data = data[n:]
	}
	return nil
}

func readFileBytes(conn net.Conn, data []byte) error {
	for len(data) > 0 {
		if err := conn.SetReadDeadline(time.Now().Add(fileIOTimeout)); err != nil {
			return err
		}
		n, err := conn.Read(data)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrUnexpectedEOF
		}
		data = data[n:]
	}
	return nil
}

func receiveFileControl(conn net.Conn) (map[string]interface{}, error) {
	var header [4]byte
	if err := readFileBytes(conn, header[:]); err != nil {
		return nil, err
	}
	size := binary.BigEndian.Uint32(header[:])
	if size == 0 || size > maxFileControl {
		return nil, errors.New("invalid file control frame size")
	}
	body := make([]byte, size)
	if err := readFileBytes(conn, body); err != nil {
		return nil, err
	}
	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, err
	}
	if result == nil {
		return nil, errors.New("invalid file control frame")
	}
	return result, nil
}

// The auxiliary greeting is an RCHSocket length-prefixed JSON frame, not a
// file-control frame. All following data uses the Python file_stream format.
func SendFileDataGreeting(conn net.Conn, id, token string) error {
	packet, err := json.Marshal(map[string]string{"type": "transfer_data", "transfer_id": id, "token": token})
	if err != nil {
		return err
	}
	if len(packet) == 0 || len(packet) > maxFileGreeting {
		return errors.New("invalid auxiliary greeting")
	}
	var header [4]byte
	binary.LittleEndian.PutUint32(header[:], uint32(len(packet)))
	if err = writeFileBytes(conn, header[:]); err != nil {
		return err
	}
	return writeFileBytes(conn, packet)
}

func ReadFileDataGreeting(conn net.Conn) (string, string, error) {
	var header [4]byte
	if err := readFileBytes(conn, header[:]); err != nil {
		return "", "", err
	}
	size := binary.LittleEndian.Uint32(header[:])
	if size == 0 || size > maxFileGreeting {
		return "", "", errors.New("invalid auxiliary greeting")
	}
	body := make([]byte, size)
	if err := readFileBytes(conn, body); err != nil {
		return "", "", err
	}
	var packet struct {
		Type  string `json:"type"`
		ID    string `json:"transfer_id"`
		Token string `json:"token"`
	}
	if err := json.Unmarshal(body, &packet); err != nil {
		return "", "", err
	}
	if packet.Type != "transfer_data" || packet.ID == "" || packet.Token == "" {
		return "", "", errors.New("invalid file data greeting")
	}
	return packet.ID, packet.Token, nil
}

func cancelFileSocket(ctx context.Context, conn net.Conn) func() {
	done := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.Close()
		case <-done:
		}
	}()
	return func() { close(done) }
}

func sendTCPFile(ctx context.Context, conn net.Conn, path string, fields map[string]interface{}, progress func(int64, int64)) (int64, error) {
	source, err := os.Open(path)
	if err != nil {
		return 0, err
	}
	defer source.Close()
	stat, err := source.Stat()
	if err != nil {
		return 0, err
	}
	size := stat.Size()
	if size < 0 || !stat.Mode().IsRegular() {
		return 0, errors.New("not a regular file")
	}
	header := map[string]interface{}{"size": size}
	for k, v := range fields {
		header[k] = v
	}
	if err = writeFileControl(conn, header); err != nil {
		return 0, err
	}
	hash := sha256.New()
	sent := int64(0)
	buffer := make([]byte, config.Runtime().TransferBufferSize())
	for sent < size {
		if err = ctx.Err(); err != nil {
			return 0, err
		}
		remaining := size - sent
		chunkSize := len(buffer)
		if remaining < int64(chunkSize) {
			chunkSize = int(remaining)
		}
		n, readErr := io.ReadFull(source, buffer[:chunkSize])
		if readErr != nil {
			return 0, readErr
		}
		if err = writeFileBytes(conn, buffer[:n]); err != nil {
			return 0, err
		}
		_, _ = hash.Write(buffer[:n])
		sent += int64(n)
		if progress != nil {
			progress(sent, size)
		}
	}
	if err = ctx.Err(); err != nil {
		return 0, err
	}
	var extra [1]byte
	if n, _ := source.Read(extra[:]); n != 0 {
		return 0, errors.New("source file changed during transfer")
	}
	if err = writeFileControl(conn, map[string]interface{}{"sha256": hex.EncodeToString(hash.Sum(nil))}); err != nil {
		return 0, err
	}
	return sent, nil
}

func receiveTCPFile(ctx context.Context, conn net.Conn, file *os.File, header map[string]interface{}, progress func(int64, int64)) (int64, error) {
	// JSON decodes numbers as float64. Accept only an exact nonnegative integer.
	declared, ok := header["size"].(float64)
	if !ok || declared < 0 || declared > float64(1<<53) || declared != float64(int64(declared)) {
		return 0, errors.New("invalid declared file size")
	}
	total := int64(declared)
	hash := sha256.New()
	received := int64(0)
	buffer := make([]byte, config.Runtime().TransferBufferSize())
	for received < total {
		if err := ctx.Err(); err != nil {
			return 0, err
		}
		amount := len(buffer)
		if total-received < int64(amount) {
			amount = int(total - received)
		}
		if err := readFileBytes(conn, buffer[:amount]); err != nil {
			return 0, err
		}
		if _, err := file.Write(buffer[:amount]); err != nil {
			return 0, err
		}
		_, _ = hash.Write(buffer[:amount])
		received += int64(amount)
		if progress != nil {
			progress(received, total)
		}
	}
	tail, err := receiveFileControl(conn)
	if err != nil {
		return 0, err
	}
	if tail["sha256"] != hex.EncodeToString(hash.Sum(nil)) {
		return 0, errors.New("file checksum mismatch")
	}
	if err = ctx.Err(); err != nil {
		return 0, err
	}
	return received, nil
}

func (s *Session) uploadTransferFileTCP(ctx context.Context, id, path, filename, typ, category string) error {
	_, err := s.uploadTransferFileTCPExtra(ctx, id, path, filename, typ, category, nil)
	return err
}

func (s *Session) uploadTransferFileTCPExtra(ctx context.Context, id, path, filename, typ, category string, extra map[string]interface{}) (map[string]interface{}, error) {
	conn, err := s.openFileData(ctx, id)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	stop := cancelFileSocket(ctx, conn)
	defer stop()
	if extra == nil {
		extra = map[string]interface{}{}
	}
	fields := map[string]interface{}{"filename": filename, "artifact_type": typ, "category": category, "extra": extra}
	s.transferUpdate(id, map[string]interface{}{"stage": "transferring", "filename": filename, "progress_supported": true})
	size, err := sendTCPFile(ctx, conn, path, fields, func(n, total int64) {
		s.transferUpdate(id, map[string]interface{}{"stage": "transferring", "filename": filename, "transferred_bytes": n, "total_bytes": total})
	})
	if err != nil {
		return nil, err
	}
	ack, err := receiveFileControl(conn)
	if err != nil {
		return nil, err
	}
	if ack["ok"] != true {
		return nil, fmt.Errorf("TCP file upload rejected: %v", ack["error"])
	}
	data, _ := ack["data"].(map[string]interface{})
	artifactID, _ := data["artifact_id"].(string)
	if artifactID == "" {
		return nil, errors.New("TCP upload missing artifact_id")
	}
	s.transferUpdate(id, map[string]interface{}{"state": "completed", "stage": "completed", "filename": filename, "total_bytes": size, "transferred_bytes": size, "artifact_id": artifactID, "progress_supported": true})
	return data, nil
}

func (s *Session) downloadTransferFileTCP(ctx context.Context, id string, payload map[string]interface{}) error {
	release, err := acquireFilesystemMutation(ctx)
	if err != nil {
		return err
	}
	defer release()
	filename, err := safeTransferFilename(payloadText(payload["filename"]))
	if err != nil {
		return err
	}
	saveDir, err := remotePath(s, payloadText(payload["save_dir"]))
	if err != nil {
		return err
	}
	policy, specified := payload["conflict_policy"].(string)
	if payload["conflict_policy"] != nil && !specified {
		return errors.New("invalid upload conflict policy")
	}
	if specified && !validRemoteUploadPolicy(policy) {
		return errors.New("invalid upload conflict policy")
	}
	if err = os.MkdirAll(saveDir, 0755); err != nil {
		return err
	}
	stat, err := os.Stat(saveDir)
	if err != nil {
		return err
	}
	if !stat.IsDir() {
		return errors.New("save_dir is not a directory")
	}
	target := filepath.Join(saveDir, filename)
	if _, err = os.Lstat(target); err == nil && (!specified || policy == "stop") {
		return fmt.Errorf("target already exists: %s", target)
	} else if err != nil && !os.IsNotExist(err) {
		return err
	}
	tmp, err := os.CreateTemp(saveDir, ".rch-transfer-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	defer tmp.Close()
	conn, err := s.openFileData(ctx, id)
	if err != nil {
		return err
	}
	defer conn.Close()
	stop := cancelFileSocket(ctx, conn)
	defer stop()
	header, err := receiveFileControl(conn)
	if err != nil {
		return err
	}
	s.transferUpdate(id, map[string]interface{}{"stage": "transferring", "filename": filename, "progress_supported": true})
	size, err := receiveTCPFile(ctx, conn, tmp, header, func(n, total int64) {
		s.transferUpdate(id, map[string]interface{}{"stage": "transferring", "filename": filename, "transferred_bytes": n, "total_bytes": total})
	})
	if err != nil {
		return err
	}
	if err = tmp.Sync(); err != nil {
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	// Preserve the existing conflict policy at the final commit boundary.
	if err = ctx.Err(); err != nil {
		return err
	}
	if specified {
		target, err = stageRemoteTransferFile(ctx, tmp.Name(), target, policy)
	} else {
		err = os.Link(tmp.Name(), target)
	}
	if err != nil {
		return err
	}
	// A committed transfer is acknowledged even if cancellation races after commit.
	_ = writeFileControl(conn, map[string]interface{}{"ok": true, "size": size})
	s.transferUpdate(id, map[string]interface{}{"state": "completed", "stage": "completed", "filename": filename, "destination_path": target, "transferred_bytes": size, "total_bytes": size, "progress_supported": true})
	return nil
}
