package executor

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"strings"
)

func remoteZipDestination(ctx context.Context, archivePath, destination, entryName string) (string, string, error) {
	archive, err := openZipBounded(archivePath, 1<<63-1, maxZipExtractEntries)
	if err != nil {
		return "", "", err
	}
	defer archive.Close()
	if len(archive.File) == 0 {
		return "", "", fmt.Errorf("ZIP archive is empty")
	}
	seen := map[string]bool{}
	tops := map[string]bool{}
	rootFile := false
	hasEntry := false
	entryFile := false
	entryChildren := false
	requested := ""
	if entryName != "" {
		requested, err = safeZipEntry(entryName)
		if err != nil {
			return "", "", err
		}
		if requested == "" {
			return "", "", fmt.Errorf("invalid ZIP entry selection")
		}
	}
	var total uint64
	for _, file := range archive.File {
		if err := ctx.Err(); err != nil {
			return "", "", err
		}
		name, err := safeZipEntry(file.Name)
		if err != nil {
			return "", "", err
		}
		if isZipSymlink(file) {
			return "", "", fmt.Errorf("ZIP symlink entries are not allowed")
		}
		total += file.UncompressedSize64
		if total > uint64(maxZipExtractBytes) {
			return "", "", fmt.Errorf("ZIP exceeds byte limit")
		}
		if seen[name] && name != "" {
			return "", "", fmt.Errorf("duplicate ZIP entry paths")
		}
		seen[name] = true
		if name == "" {
			continue
		}
		top := strings.Split(name, "/")[0]
		tops[top] = true
		if top == name && !isZipDir(file) {
			rootFile = true
		}
		if requested != "" {
			if name == requested {
				hasEntry = true
				if !isZipDir(file) {
					entryFile = true
				}
			}
			if strings.HasPrefix(name, requested+"/") {
				entryChildren = true
			}
		}
	}
	if requested != "" {
		if entryFile && entryChildren {
			return "", "", fmt.Errorf("ambiguous ZIP selection")
		}
		if !hasEntry && !entryChildren {
			return "", "", fmt.Errorf("ZIP entry not found")
		}
		kind := "directory"
		if entryFile {
			kind = "file"
		}
		return filepath.Join(destination, path.Base(requested)), kind, nil
	}
	name := strings.TrimSuffix(filepath.Base(archivePath), filepath.Ext(archivePath))
	if len(tops) == 1 && !rootFile {
		for root := range tops {
			name = root
		}
	}
	if name == "" {
		name = "archive"
	}
	return filepath.Join(destination, name), "directory", nil
}
func extractRemoteZipPolicy(ctx context.Context, s *Session, payload map[string]interface{}) (int, interface{}) {
	archivePath, err := remoteExisting(s, payloadText(payload["path"]), false)
	if err != nil {
		return 0, err.Error()
	}
	destination, err := remoteExisting(s, payloadText(payload["destination_dir"]), true)
	if err != nil {
		return 0, err.Error()
	}
	entry := payloadText(payload["entry_name"])
	target, srcKind, err := remoteZipDestination(ctx, archivePath, destination, entry)
	if err != nil {
		return 0, err.Error()
	}
	destKind, err := remoteKind(target)
	if err != nil {
		return 0, err.Error()
	}
	conflict := []map[string]interface{}{}
	if destKind != "" {
		conflict = append(conflict, map[string]interface{}{
			"source": archivePath, "target": target, "source_kind": srcKind, "target_kind": destKind,
			"allowed_actions": remoteAllowed(srcKind, destKind),
		})
	}
	if payloadBool(payload["inspect"]) {
		return 1, map[string]interface{}{"conflicts": conflict, "target": target}
	}
	policy := "stop"
	if supplied, exists := payload["conflict_policy"]; exists {
		provided, ok := supplied.(string)
		if !ok {
			return 0, "invalid conflict policy"
		}
		policy = provided
	}
	if policy != "stop" && policy != "skip" && policy != "replace" && policy != "merge" && policy != "keep_both" {
		return 0, "invalid conflict policy"
	}
	if destKind != "" && !remoteActionAllowed(srcKind, destKind, policy) {
		return 0, "invalid conflict policy for target"
	}
	if destKind != "" && policy == "skip" {
		return 1, map[string]interface{}{"skipped": true, "destination_dir": destination,
			"extracted_to": target, "file_count": 0, "dir_count": 0}
	}
	stage, err := os.MkdirTemp(destination, ".rch-zip-stage-*")
	if err != nil {
		return 0, err.Error()
	}
	defer os.RemoveAll(stage)
	legacy := map[string]interface{}{"path": archivePath, "destination_dir": stage, "entry_name": entry}
	status, out := extractRemoteZipStaged(ctx, s, legacy)
	if status != 1 {
		return status, out
	}
	result, ok := out.(map[string]interface{})
	if !ok {
		return 0, "invalid ZIP extract result"
	}
	extracted, ok := result["extracted_to"].(string)
	if !ok {
		return 0, "invalid ZIP extract result"
	}
	if destKind != "" && policy == "keep_both" {
		unique, err := remoteUniqueTarget(target)
		if err != nil {
			return 0, err.Error()
		}
		target = unique
		policy = "stop"
	}
	if err := applyRemoteConflict(ctx, extracted, target, "move", policy); err != nil {
		if errors.Is(err, errRemoteSkipped) {
			return 1, map[string]interface{}{"skipped": true, "destination_dir": destination,
				"extracted_to": target, "file_count": 0, "dir_count": 0}
		}
		return 0, err.Error()
	}
	if policy == "keep_both" && destKind != "" {
		// The committed name is chosen by applyRemoteConflict; locate the created path from stage comparison.
		// The follow-up listing is refreshed by the browser; extracted_to may remain the requested name.
	}
	result["destination_dir"] = destination
	result["extracted_to"] = target
	return 1, result
}
