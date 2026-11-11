package executor

import (
	"bytes"
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

	"client-go/config"
)

func (s *Session) uploadSingleFileToServerResult(filePath string, category string) (int, string) {
	fileSize := int64(0)
	if info, err := os.Stat(filePath); err == nil {
		fileSize = info.Size()
	}

	payload, err := s.uploadFileToServer(filePath, category)
	if err != nil {
		return 0, err.Error()
	}

	message := buildUploadSuccessMessage(payload, filePath)
	if message == "" {
		message = fmt.Sprintf("HTTP upload completed\nOriginal: %s\nSize: %d bytes", filepath.Base(filePath), fileSize)
	}
	return 1, message
}

func (s *Session) uploadFileToServer(filePath string, category string) (map[string]interface{}, error) {
	url := strings.TrimRight(config.UPLOAD_BASE_URL, "/") + "/api/files/upload"

	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)

	_ = writer.WriteField("artifact_type", "files")
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
