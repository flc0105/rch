package executor

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func remoteKind(path string) (string, error) {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return "link", nil
	}
	if info.IsDir() {
		return "directory", nil
	}
	return "file", nil
}
func remoteAllowed(src, dest string) []string {
	if dest == "" {
		return []string{}
	}
	if src == "directory" && dest == "directory" {
		return []string{"stop", "merge", "replace", "keep_both"}
	}
	if src == "file" && dest == "file" {
		return []string{"stop", "replace", "keep_both"}
	}
	return []string{"stop", "keep_both"}
}
func remoteActionAllowed(src, dest, policy string) bool {
	for _, v := range remoteAllowed(src, dest) {
		if v == policy {
			return true
		}
	}
	return false
}
func remoteConflict(src, target string, index int) (map[string]interface{}, error) {
	sourceKind, err := remoteKind(src)
	if err != nil {
		return nil, err
	}
	targetKind, err := remoteKind(target)
	if err != nil {
		return nil, err
	}
	if targetKind == "" {
		return nil, nil
	}
	return map[string]interface{}{
		"source": src, "target": target, "source_kind": sourceKind, "target_kind": targetKind,
		"allowed_actions": remoteAllowed(sourceKind, targetKind), "index": index,
	}, nil
}
func remoteUniqueTarget(target string) (string, error) {
	name := filepath.Base(target)
	ext := filepath.Ext(name)
	stem := strings.TrimSuffix(name, ext)
	stamp := time.Now().Format("20060102_150405")
	for i := 0; i < 128; i++ {
		seed := make([]byte, 16)
		if _, err := rand.Read(seed); err != nil {
			return "", err
		}
		hash := sha256.Sum256(append(seed, []byte(target)...))
		candidate := filepath.Join(filepath.Dir(target), fmt.Sprintf("%s_%s_%s%s", stem, stamp, hex.EncodeToString(hash[:4]), ext))
		kind, err := remoteKind(candidate)
		if err != nil {
			return "", err
		}
		if kind == "" {
			return candidate, nil
		}
	}
	return "", fmt.Errorf("could not choose unique name")
}
func remoteMerge(ctx context.Context, src, dest string, dry bool) error {
	return filepath.Walk(src, func(path string, info os.FileInfo, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		rel, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}
		target := filepath.Join(dest, rel)
		existing, err := remoteKind(target)
		if err != nil {
			return err
		}
		kind := "file"
		if info.IsDir() {
			kind = "directory"
		}
		if info.Mode()&os.ModeSymlink != 0 {
			kind = "link"
		}
		if existing != "" && (existing != kind || kind == "link") {
			return fmt.Errorf("incompatible merge target: %s", target)
		}
		if dry {
			return nil
		}
		if kind == "directory" {
			return os.MkdirAll(target, info.Mode().Perm())
		}
		if kind == "link" {
			return copyRemotePath(ctx, path, target)
		}
		temp, err := os.CreateTemp(filepath.Dir(target), ".rch-file-*")
		if err != nil {
			return err
		}
		tmp := temp.Name()
		_ = temp.Close()
		_ = os.Remove(tmp)
		defer os.Remove(tmp)
		if err := copyRemotePath(ctx, path, tmp); err != nil {
			return err
		}
		if existing == "" {
			return os.Rename(tmp, target)
		}
		slot, err := os.MkdirTemp(filepath.Dir(target), ".rch-merge-*")
		if err != nil {
			return err
		}
		defer os.RemoveAll(slot)
		backup := filepath.Join(slot, "old")
		if err := os.Rename(target, backup); err != nil {
			return err
		}
		if err := os.Rename(tmp, target); err != nil {
			_ = os.Rename(backup, target)
			return err
		}
		return nil
	})
}
func applyRemoteConflict(ctx context.Context, source, target, operation, policy string) error {
	if policy != "stop" && policy != "replace" && policy != "merge" && policy != "keep_both" {
		return fmt.Errorf("invalid conflict policy")
	}
	source, _ = filepath.Abs(source)
	target, _ = filepath.Abs(target)
	if source == target {
		if policy != "keep_both" {
			return fmt.Errorf("source and target are the same")
		}
		// Copy into the source folder is a valid Keep Both operation.
		unique, err := remoteUniqueTarget(target)
		if err != nil {
			return err
		}
		target = unique
	}
	srcKind, err := remoteKind(source)
	if err != nil {
		return err
	}
	if srcKind == "" {
		return os.ErrNotExist
	}
	if srcKind == "directory" {
		rel, err := filepath.Rel(source, target)
		if err != nil {
			return err
		}
		if rel == "." || (rel != ".." && !strings.HasPrefix(rel, ".."+string(os.PathSeparator)) && !filepath.IsAbs(rel)) {
			return fmt.Errorf("cannot operate on directory within itself")
		}
	}
	destKind, err := remoteKind(target)
	if err != nil {
		return err
	}
	if destKind != "" {
		if !remoteActionAllowed(srcKind, destKind, policy) {
			return fmt.Errorf("target already exists: %s", target)
		}
		if policy == "stop" {
			return fmt.Errorf("target already exists: %s", target)
		}
		if policy == "keep_both" {
			target, err = remoteUniqueTarget(target)
			if err != nil {
				return err
			}
			destKind = ""
		}
	}
	if destKind != "" && policy == "merge" {
		if err := remoteMerge(ctx, source, target, true); err != nil {
			return err
		}
		if err := remoteMerge(ctx, source, target, false); err != nil {
			return err
		}
		if operation == "move" {
			return deleteRemotePath(ctx, source)
		}
		return nil
	}
	if destKind != "" && policy == "replace" {
		stage, err := os.MkdirTemp(filepath.Dir(target), ".rch-conflict-*")
		if err != nil {
			return err
		}
		defer os.RemoveAll(stage)
		incoming := filepath.Join(stage, "incoming")
		if err := copyRemotePath(ctx, source, incoming); err != nil {
			return err
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		backup := filepath.Join(stage, "old")
		if err := os.Rename(target, backup); err != nil {
			return err
		}
		if err := os.Rename(incoming, target); err != nil {
			_ = os.Rename(backup, target)
			return err
		}
		if operation == "move" {
			return deleteRemotePath(ctx, source)
		}
		return nil
	}
	if operation == "move" {
		if err := os.Rename(source, target); err == nil {
			return nil
		}
	}
	if err := copyRemotePath(ctx, source, target); err != nil {
		return err
	}
	if operation == "move" {
		return deleteRemotePath(ctx, source)
	}
	return nil
}

func validRemoteUploadPolicy(policy string) bool {
	return policy == "stop" || policy == "replace" || policy == "keep_both"
}

// stageRemoteTransferFile commits completed transfer files without unrequested overwrites.
func stageRemoteTransferFile(ctx context.Context, tmp, target, policy string) error {
	if !validRemoteUploadPolicy(policy) {
		return fmt.Errorf("invalid upload conflict policy")
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	kind, err := remoteKind(target)
	if err != nil {
		return err
	}
	if kind != "" && !remoteActionAllowed("file", kind, policy) {
		return fmt.Errorf("target already exists: %s", target)
	}
	switch {
	case kind != "" && policy == "replace":
		// A staged swap works on Windows too, where Rename cannot replace an open target.
		slot, err := os.MkdirTemp(filepath.Dir(target), ".rch-upload-replace-*")
		if err != nil {
			return err
		}
		defer os.RemoveAll(slot)
		backup := filepath.Join(slot, "old")
		if err := os.Rename(target, backup); err != nil {
			return err
		}
		if err := os.Rename(tmp, target); err != nil {
			_ = os.Rename(backup, target)
			return err
		}
		return nil
	case kind != "" && policy == "keep_both":
		for i := 0; i < 8; i++ {
			unique, err := remoteUniqueTarget(target)
			if err != nil {
				return err
			}
			if err := os.Link(tmp, unique); os.IsExist(err) {
				continue
			} else {
				return err
			}
		}
		return fmt.Errorf("could not allocate unique name")
	default:
		return os.Link(tmp, target)
	}
}

func inspectRemoteUpload(s *Session, args []string) (int, string) {
	raw := strings.TrimSpace(strings.Join(args, " "))
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, err.Error()
	}
	name := payloadText(payload["filename"])
	if _, err := safeTransferFilename(name); err != nil {
		return 0, err.Error()
	}
	directory, err := remoteExisting(s, payloadText(payload["destination_dir"]), true)
	if err != nil {
		return 0, err.Error()
	}
	target := filepath.Join(directory, name)
	kind, err := remoteKind(target)
	if err != nil {
		return 0, err.Error()
	}
	conflicts := []map[string]interface{}{}
	if kind != "" {
		conflicts = append(conflicts, map[string]interface{}{
			"source": name, "target": target, "source_kind": "file", "target_kind": kind,
			"allowed_actions": remoteAllowed("file", kind),
		})
	}
	return jsonResult(map[string]interface{}{"conflicts": conflicts})
}
