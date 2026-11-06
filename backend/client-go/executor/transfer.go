package executor

import (
	"archive/zip"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"client-go/config"
)

// Transfers are independent of the foreground command slot. The Server owns
// the Transfer Center lifecycle; the Client reports state over the same socket.
type transferState struct {
	cancel context.CancelFunc
}

type transferTracker struct {
	mu     sync.Mutex
	active map[string]*transferState
}

func (t *transferTracker) start(id string, cancel context.CancelFunc) bool {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.active == nil {
		t.active = make(map[string]*transferState)
	}
	if _, exists := t.active[id]; exists {
		return false
	}
	t.active[id] = &transferState{cancel: cancel}
	return true
}

func (t *transferTracker) stop(id string) {
	t.mu.Lock()
	item := t.active[id]
	t.mu.Unlock()
	if item != nil {
		item.cancel()
	}
}

func (t *transferTracker) finish(id string) {
	t.mu.Lock()
	delete(t.active, id)
	t.mu.Unlock()
}

func (t *transferTracker) close() {
	t.mu.Lock()
	all := make([]context.CancelFunc, 0, len(t.active))
	for _, item := range t.active {
		all = append(all, item.cancel)
	}
	t.mu.Unlock()
	for _, cancel := range all {
		cancel()
	}
}

func (s *Session) CloseTransfers()          { s.transfers.close() }
func (s *Session) CancelTransfer(id string) { s.transfers.stop(strings.TrimSpace(id)) }

func (s *Session) transferUpdate(id string, fields map[string]interface{}) {
	msg := map[string]interface{}{"type": "transfer_update", "transfer_id": id}
	for k, v := range fields {
		msg[k] = v
	}
	_ = s.Sock.Send(msg)
}

func (s *Session) StartTransfer(id, operation string, payload map[string]interface{}) {
	id = strings.TrimSpace(id)
	if id == "" {
		return
	}
	allowed := map[string]bool{
		"client_to_server_file":    true,
		"client_to_server_preview": true,
		"client_to_server_zip":     true,
		"server_to_client_file":    true,
	}
	if !allowed[operation] {
		s.transferUpdate(id, map[string]interface{}{"state": "failed", "stage": "failed", "cancel_supported": false, "error": "Unsupported transfer operation: " + operation})
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	if !s.transfers.start(id, cancel) {
		cancel()
		return
	}
	go func() {
		defer cancel()
		defer s.transfers.finish(id)
		s.transferUpdate(id, map[string]interface{}{"state": "running", "cancel_supported": true, "progress_supported": true})
		err := s.runTransfer(ctx, id, operation, payload)
		if err == nil {
			return
		}
		if errors.Is(err, context.Canceled) || ctx.Err() != nil {
			s.transferUpdate(id, map[string]interface{}{"state": "cancelled", "stage": "cancelled", "error": ""})
		} else {
			s.transferUpdate(id, map[string]interface{}{"state": "failed", "stage": "failed", "error": err.Error()})
		}
	}()
}

func (s *Session) runTransfer(ctx context.Context, id, operation string, payload map[string]interface{}) error {
	switch operation {
	case "client_to_server_file", "client_to_server_preview":
		path, err := remoteExisting(s, payloadText(payload["path"]), false)
		if err != nil {
			return err
		}
		info, err := os.Stat(path)
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return fmt.Errorf("not a regular file: %s", path)
		}
		typ, category := "files", "download"
		if operation == "client_to_server_preview" {
			typ, category = "previews", "preview_cache"
		}
		if operation == "client_to_server_file" {
			if v := payloadText(payload["artifact_type"]); v != "" {
				typ = v
			}
			if v := payloadText(payload["category"]); v != "" {
				category = v
			}
		}
		return s.uploadTransferFile(ctx, id, path, filepath.Base(path), typ, category)
	case "client_to_server_zip":
		paths, err := pathsForTransfer(s, payload["paths"])
		if err != nil {
			return err
		}
		tmp, err := os.CreateTemp("", "rch-go-transfer-*.zip")
		if err != nil {
			return err
		}
		name := tmp.Name()
		_ = tmp.Close()
		_ = os.Remove(name)
		defer os.Remove(name)
		s.transferUpdate(id, map[string]interface{}{"state": "running", "stage": "preparing"})
		if err := writeZipPaths(ctx, name, paths); err != nil {
			return err
		}
		filename := payloadText(payload["archive_name"])
		if filename == "" {
			filename = "selected_files.zip"
		}
		filename, err = safeTransferFilename(filename)
		if err != nil {
			return err
		}
		if !strings.HasSuffix(strings.ToLower(filename), ".zip") {
			filename += ".zip"
		}
		return s.uploadTransferFile(ctx, id, name, filename, "files", "bundle")
	case "server_to_client_file":
		return s.downloadTransferFile(ctx, id, payload)
	default:
		return fmt.Errorf("unsupported transfer: %s", operation)
	}
}

func pathsForTransfer(s *Session, raw interface{}) ([]string, error) {
	list, ok := raw.([]interface{})
	if !ok || len(list) == 0 {
		return nil, errors.New("paths is required")
	}
	result := make([]string, 0, len(list))
	for _, value := range list {
		name, ok := value.(string)
		if !ok || strings.TrimSpace(name) == "" {
			return nil, errors.New("invalid transfer path")
		}
		resolved, err := remoteExisting(s, name, false)
		if err != nil {
			return nil, err
		}
		result = append(result, resolved)
	}
	return result, nil
}

// This is a trusted endpoint explicitly configured by Agent Builder. Caller-
// provided absolute URLs cannot redirect a transfer to an arbitrary origin.
func transferURL(relative string) (string, error) {
	base, err := url.Parse(strings.TrimRight(config.UPLOAD_BASE_URL, "/") + "/")
	if err != nil || (base.Scheme != "http" && base.Scheme != "https") || base.Host == "" {
		return "", errors.New("invalid Server Web URL")
	}
	value, err := url.Parse(strings.TrimSpace(relative))
	if err != nil || value.IsAbs() || value.Host != "" || strings.HasPrefix(relative, "//") || !strings.HasPrefix(relative, "/") {
		return "", errors.New("file transfer requires a Server-relative URL")
	}
	return base.ResolveReference(value).String(), nil
}

func transferHTTPClient() *http.Client {
	return &http.Client{Transport: &http.Transport{Proxy: http.ProxyFromEnvironment, MaxIdleConnsPerHost: 2, ResponseHeaderTimeout: 45 * time.Second}, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
}

// progressReader counts actual file bytes, not multipart overhead.
type progressReader struct {
	in     io.Reader
	read   int64
	total  int64
	report func(int64, int64)
	last   time.Time
}

func (r *progressReader) Read(p []byte) (int, error) {
	n, err := r.in.Read(p)
	if n > 0 {
		r.read += int64(n)
	}
	if r.report != nil && (time.Since(r.last) > 250*time.Millisecond || (r.total > 0 && r.read >= r.total)) {
		r.last = time.Now()
		r.report(r.read, r.total)
	}
	return n, err
}

func (s *Session) uploadTransferFile(ctx context.Context, id, filePath, filename, artifactType, category string) error {
	file, err := os.Open(filePath)
	if err != nil {
		return err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return err
	}
	uploadURL, err := transferURL("/api/files/upload")
	if err != nil {
		return err
	}
	total := info.Size()
	s.transferUpdate(id, map[string]interface{}{"state": "running", "stage": "staging", "filename": filename, "total_bytes": total, "transferred_bytes": int64(0), "progress_supported": true})
	bodyReader, bodyWriter := io.Pipe()
	writer := multipart.NewWriter(bodyWriter)
	done := make(chan error, 1)
	go func() {
		defer bodyWriter.Close()
		fields := map[string]string{"artifact_type": artifactType, "category": category, "client_id": s.ClientID, "hostname": s.HostName}
		for key, value := range fields {
			if err := writer.WriteField(key, value); err != nil {
				done <- err
				_ = bodyWriter.CloseWithError(err)
				return
			}
		}
		part, err := writer.CreateFormFile("file", filename)
		if err == nil {
			_, err = io.Copy(part, &progressReader{in: file, total: total, report: func(n, all int64) {
				s.transferUpdate(id, map[string]interface{}{"state": "running", "stage": "staging", "filename": filename, "transferred_bytes": n, "total_bytes": all, "progress_supported": true})
			}})
		}
		if err == nil {
			err = writer.Close()
		}
		if err != nil {
			_ = bodyWriter.CloseWithError(err)
		}
		done <- err
	}()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, uploadURL, bodyReader)
	if err != nil {
		_ = bodyReader.CloseWithError(err)
		<-done
		return err
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	resp, err := transferHTTPClient().Do(req)
	if err != nil {
		_ = bodyReader.CloseWithError(err)
		<-done
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		_ = bodyReader.CloseWithError(errors.New("HTTP upload rejected"))
	}
	if err := <-done; err != nil && resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return err
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 65536))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("HTTP upload: %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	var envelope struct {
		Code    int    `json:"code"`
		Message string `json:"message"`
		Data    struct {
			ArtifactID string `json:"artifact_id"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &envelope); err != nil {
		return err
	}
	if envelope.Code != 0 {
		return fmt.Errorf("HTTP upload: %s", envelope.Message)
	}
	if strings.TrimSpace(envelope.Data.ArtifactID) == "" {
		return errors.New("upload completed without artifact_id")
	}
	s.transferUpdate(id, map[string]interface{}{"state": "completed", "stage": "completed", "filename": filename, "total_bytes": total, "transferred_bytes": total, "artifact_id": envelope.Data.ArtifactID, "progress_supported": true})
	return nil
}

func safeTransferFilename(raw string) (string, error) {
	if raw == "" || raw == "." || raw == ".." || strings.ContainsAny(raw, "/\\\x00") || filepath.Base(raw) != raw {
		return "", errors.New("invalid remote filename")
	}
	return raw, nil
}

func (s *Session) downloadTransferFile(ctx context.Context, id string, payload map[string]interface{}) error {
	filename, err := safeTransferFilename(payloadText(payload["filename"]))
	if err != nil {
		return err
	}
	// Server controls the temporary download path; it is always relative to
	// this Client's configured Web Server, not an arbitrary third-party URL.
	relative := payloadText(payload["relative_url"])
	if relative == "" {
		return errors.New("relative_url is required")
	}
	downloadURL, err := transferURL(relative)
	if err != nil {
		return err
	}
	saveDir, err := remotePath(s, payloadText(payload["save_dir"]))
	if err != nil {
		return err
	}
	if err := os.MkdirAll(saveDir, 0755); err != nil {
		return err
	}
	info, err := os.Stat(saveDir)
	if err != nil {
		return err
	}
	if !info.IsDir() {
		return errors.New("save_dir is not a directory")
	}
	target := filepath.Join(saveDir, filename)
	if _, err := os.Lstat(target); err == nil {
		return fmt.Errorf("target already exists: %s", target)
	} else if !os.IsNotExist(err) {
		return err
	}
	s.transferUpdate(id, map[string]interface{}{"state": "running", "stage": "transferring", "filename": filename, "transferred_bytes": int64(0), "progress_supported": true})
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, downloadURL, nil)
	if err != nil {
		return err
	}
	resp, err := transferHTTPClient().Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("HTTP download: %d", resp.StatusCode)
	}
	tmp, err := os.CreateTemp(saveDir, ".rch-transfer-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	defer tmp.Close()
	total := resp.ContentLength
	if total < 0 {
		total = 0
	}
	reader := &progressReader{in: resp.Body, total: total, report: func(n, all int64) {
		s.transferUpdate(id, map[string]interface{}{"state": "running", "stage": "transferring", "filename": filename, "transferred_bytes": n, "total_bytes": all, "progress_supported": true})
	}}
	size, err := io.Copy(tmp, reader)
	if err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if total > 0 && size != total {
		return fmt.Errorf("download size mismatch: %d != %d", size, total)
	}
	if err := tmp.Sync(); err != nil {
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	// Link ensures a concurrent file creation cannot be silently overwritten.
	if err := os.Link(tmp.Name(), target); err != nil {
		return err
	}
	s.transferUpdate(id, map[string]interface{}{"state": "completed", "stage": "completed", "filename": filename, "transferred_bytes": size, "total_bytes": size, "progress_supported": true})
	return nil
}

// Kept here because these helpers are shared with ZIP uploads.
func writeZipPaths(ctx context.Context, target string, paths []string) (retErr error) {
	out, err := os.OpenFile(target, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	// On error or cancellation, never leave a corrupt archive at its final path.
	defer func() {
		if err := out.Close(); retErr == nil && err != nil {
			retErr = err
		}
		if retErr != nil {
			_ = os.Remove(target)
		}
	}()
	archive := zip.NewWriter(out)
	usedRoots := make(map[string]bool)
	for _, source := range paths {
		base := filepath.Base(source)
		rootName := base
		for suffix := 1; usedRoots[rootName]; suffix++ {
			rootName = fmt.Sprintf("%s_%d", base, suffix)
		}
		usedRoots[rootName] = true
		err = filepath.Walk(source, func(path string, info os.FileInfo, walkErr error) error {
			if walkErr != nil {
				return walkErr
			}
			if err := ctx.Err(); err != nil {
				return err
			}
			relative, err := filepath.Rel(source, path)
			if err != nil {
				return err
			}
			name := rootName
			if relative != "." {
				name = filepath.ToSlash(filepath.Join(rootName, relative))
			}
			if info.Mode()&os.ModeSymlink != 0 {
				return fmt.Errorf("ZIP symlinks are not supported: %s", path)
			}
			if info.IsDir() {
				_, err = archive.Create(name + "/")
				return err
			}
			if !info.Mode().IsRegular() {
				return fmt.Errorf("unsupported ZIP entry: %s", path)
			}
			header, err := zip.FileInfoHeader(info)
			if err != nil {
				return err
			}
			header.Name = name
			header.Method = zip.Deflate
			writer, err := archive.CreateHeader(header)
			if err != nil {
				return err
			}
			input, err := os.Open(path)
			if err != nil {
				return err
			}
			_, copyErr := io.Copy(writer, &contextReader{ctx: ctx, reader: input})
			closeErr := input.Close()
			if copyErr != nil {
				return copyErr
			}
			return closeErr
		})
		if err != nil {
			_ = archive.Close()
			return err
		}
	}
	return archive.Close()
}
