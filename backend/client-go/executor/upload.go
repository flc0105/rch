package executor

import (
	"bytes"
	"client-go/config"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

func (s *Session) uploadSingleFileToServerResult(filePath string, category string) (int, string) {
	fileSize := int64(0)
	if info, err := os.Stat(filePath); err == nil {
		fileSize = info.Size()
	}

	var payload map[string]interface{}
	var err error
	if config.Runtime().FileTransferMode() == config.TransferTCPStreaming {
		payload, err = s.uploadCommandFileTCP(filePath, category)
	} else {
		payload, err = s.uploadFileToServer(filePath, category)
	}
	if err != nil {
		return 0, err.Error()
	}

	message := buildUploadSuccessMessage(payload, filePath)
	if message == "" {
		message = fmt.Sprintf("HTTP upload completed\nOriginal: %s\nSize: %d bytes", filepath.Base(filePath), fileSize)
	}
	return 1, message
}

func (s *Session) uploadCommandFileTCP(path, category string) (map[string]interface{}, error) {
	if s.CurrentCommandID <= 0 {
		return nil, fmt.Errorf("file transfer requires an active command")
	}
	stat, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if !stat.Mode().IsRegular() {
		return nil, fmt.Errorf("not a regular file")
	}
	var randomID [16]byte
	if _, err = rand.Read(randomID[:]); err != nil {
		return nil, err
	}
	id := hex.EncodeToString(randomID[:])
	filename := filepath.Base(path)
	ctx, cancel := context.WithCancel(context.Background())
	if !s.transfers.start(id, cancel) {
		cancel()
		return nil, fmt.Errorf("Client session is closed")
	}
	defer cancel()
	defer s.transfers.finish(id)
	registration := map[string]interface{}{
		"command_id": s.CurrentCommandID, "direction": "client_to_server", "filename": filename,
		"source_path": path, "total_bytes": stat.Size(), "file_transfer_mode": config.TransferTCPStreaming,
	}
	if err = s.registerTransfer(ctx, id, registration); err != nil {
		return nil, err
	}
	extra := map[string]interface{}{}
	if category == "screenshots" {
		extra = map[string]interface{}{"saved_from": "client_command", "source_command": "screenshot"}
	}
	data, err := s.uploadTransferFileTCPExtra(ctx, id, path, filename, "saved", defaultString(category, "inbox"), extra)
	if err != nil {
		s.transferUpdate(id, map[string]interface{}{"state": "failed", "stage": "failed", "error": err.Error()})
		return nil, err
	}
	// Transfer completion already went over the managed Transfer channel.
	return map[string]interface{}{"message": "TCP upload completed", "data": data}, nil
}

func (s *Session) uploadFileToServer(filePath string, category string) (map[string]interface{}, error) {
	url := strings.TrimRight(s.ServerWebBaseURL(), "/") + "/api/files/upload"

	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)

	_ = writer.WriteField("artifact_type", "saved")
	_ = writer.WriteField("category", defaultString(category, "inbox"))
	if category == "screenshots" {
		_ = writer.WriteField("extra", `{"saved_from":"client_command","source_command":"screenshot"}`)
	}
	_ = writer.WriteField("client_id", s.ClientID)
	_ = writer.WriteField("hostname", s.HostName)
	if s.CurrentCommandID > 0 {
		_ = writer.WriteField("source_command_id", strconv.Itoa(s.CurrentCommandID))
	}

	part, err := writer.CreateFormFile("file", filepath.Base(filePath))
	if err != nil {
		return nil, err
	}
	if _, err := io.Copy(part, file); err != nil {
		return nil, err
	}
	if err := writer.Close(); err != nil {
		return nil, err
	}

	req, err := http.NewRequest(http.MethodPost, url, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	respBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("upload failed: http %d: %s", resp.StatusCode, strings.TrimSpace(string(respBytes)))
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(respBytes, &payload); err != nil {
		return map[string]interface{}{"message": strings.TrimSpace(string(respBytes))}, nil
	}
	return payload, nil
}

func buildUploadSuccessMessage(payload map[string]interface{}, filePath string) string {
	if payload == nil {
		return ""
	}

	message := asString(payload["message"])
	if message == "" {
		message = "HTTP upload completed"
	}

	data, _ := payload["data"].(map[string]interface{})
	if data == nil {
		return message
	}

	originalName := asString(data["original_name"])
	if originalName == "" {
		originalName = filepath.Base(filePath)
	}
	storedName := asString(data["stored_name"])
	artifactID := asString(data["artifact_id"])
	downloadURL := asString(data["download_url"])

	lines := []string{message, fmt.Sprintf("Original: %s", originalName)}
	if storedName != "" {
		lines = append(lines, fmt.Sprintf("Stored: %s", storedName))
	}
	if artifactID != "" {
		lines = append(lines, fmt.Sprintf("Artifact ID: %s", artifactID))
	}
	if downloadURL != "" {
		lines = append(lines, fmt.Sprintf("Download URL: %s", downloadURL))
	}
	return strings.Join(lines, "\n")
}

func asString(v interface{}) string {
	switch x := v.(type) {
	case string:
		return x
	case fmt.Stringer:
		return x.String()
	default:
		return ""
	}
}

func defaultString(value string, fallback string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return fallback
	}
	return value
}
