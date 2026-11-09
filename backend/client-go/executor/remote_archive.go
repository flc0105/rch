package executor

import (
	"archive/zip"
	"context"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
)

const (
	maxZipPeekBytes      int64 = 2 * 1024 * 1024 * 1024
	maxZipPeekEntries          = 5000
	maxZipEntryBytes     int64 = 2 * 1024 * 1024
	maxZipExtractEntries       = 50000
	maxZipExtractBytes   int64 = 20 * 1024 * 1024 * 1024
)

var (
	_ = Register("create_zip_paths", Usage("create_zip_paths <payload>"), Help("Create a ZIP archive from selected files"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(createRemoteZip))
	_ = Register("peek_zip", Usage("peek_zip <payload>"), Help("Inspect ZIP entries"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(peekRemoteZip))
	_ = Register("read_zip_entry", Usage("read_zip_entry <payload>"), Help("Read a small ZIP text entry"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(readRemoteZipEntry))
	_ = Register("extract_zip_path", Usage("extract_zip_path <payload>"), Help("Extract ZIP into a directory"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(extractRemoteZip))
)

type zipNode struct {
	Name           string     `json:"name"`
	Path           string     `json:"path"`
	EntryName      string     `json:"entry_name"`
	IsDir          bool       `json:"is_dir"`
	Size           uint64     `json:"size"`
	CompressedSize uint64     `json:"compressed_size"`
	Children       []*zipNode `json:"children"`
}

func safeZipEntry(raw string) (string, error) {
	name := strings.ReplaceAll(raw, "\\", "/")
	if name == "" || strings.HasPrefix(name, "/") || (len(name) >= 2 && name[1] == ':' && ((name[0] >= 'A' && name[0] <= 'Z') || (name[0] >= 'a' && name[0] <= 'z'))) {
		return "", fmt.Errorf("unsafe ZIP entry: %q", raw)
	}
	for _, part := range strings.Split(name, "/") {
		if part == ".." {
			return "", fmt.Errorf("unsafe ZIP traversal: %q", raw)
		}
	}
	normalized := path.Clean(name)
	if normalized == "." {
		return "", nil
	}
	return normalized, nil
}

func openZipBounded(filePath string, maxBytes int64, maxEntries int) (*zip.ReadCloser, error) {
	info, err := os.Stat(filePath)
	if err != nil {
		return nil, err
	}
	if info.Size() > maxBytes {
		return nil, fmt.Errorf("ZIP exceeds archive size limit (%d bytes)", maxBytes)
	}
	archive, err := zip.OpenReader(filePath)
	if err != nil {
		return nil, err
	}
	if len(archive.File) > maxEntries {
		_ = archive.Close()
		return nil, fmt.Errorf("ZIP has too many entries (%d maximum)", maxEntries)
	}
	return archive, nil
}

func isZipDir(f *zip.File) bool     { return f.FileInfo().IsDir() || strings.HasSuffix(f.Name, "/") }
func isZipSymlink(f *zip.File) bool { return f.Mode()&os.ModeSymlink != 0 }

func zipTree(infos []*zip.File) ([]*zipNode, int, error) {
	roots := make([]*zipNode, 0)
	nodes := make(map[string]*zipNode)
	ensureDir := func(parts []string) *zipNode {
		var parent *zipNode
		for idx, part := range parts {
			name := strings.Join(parts[:idx+1], "/")
			n := nodes[name]
			if n == nil {
				n = &zipNode{Name: part, Path: name, IsDir: true, Children: make([]*zipNode, 0)}
				nodes[name] = n
				if parent == nil {
					roots = append(roots, n)
				} else {
					parent.Children = append(parent.Children, n)
				}
			}
			parent = n
		}
		return parent
	}
	for _, f := range infos {
		name, err := safeZipEntry(f.Name)
		if err != nil {
			return nil, 0, err
		}
		if name == "" {
			continue
		}
		parts := strings.Split(name, "/")
		if isZipDir(f) {
			if n := ensureDir(parts); n != nil {
				n.EntryName = f.Name
			}
			continue
		}
		var parent *zipNode
		if len(parts) > 1 {
			parent = ensureDir(parts[:len(parts)-1])
		}
		if nodes[name] != nil {
			continue
		}
		n := &zipNode{Name: parts[len(parts)-1], Path: name, EntryName: f.Name, Size: f.UncompressedSize64, CompressedSize: f.CompressedSize64, Children: make([]*zipNode, 0)}
		nodes[name] = n
		if parent == nil {
			roots = append(roots, n)
		} else {
			parent.Children = append(parent.Children, n)
		}
	}
	var sortNodes func([]*zipNode)
	sortNodes = func(list []*zipNode) {
		sort.Slice(list, func(i, j int) bool {
			if list[i].IsDir != list[j].IsDir {
				return list[i].IsDir
			}
			return strings.ToLower(list[i].Name) < strings.ToLower(list[j].Name)
		})
		for _, node := range list {
			sortNodes(node.Children)
		}
	}
	sortNodes(roots)
	count := 0
	for _, node := range nodes {
		if node.IsDir {
			count++
		}
	}
	return roots, count, nil
}

func peekRemoteZip(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, err.Error()
	}
	archivePath, err := remoteExisting(s, payloadText(payload["path"]), false)
	if err != nil {
		return 0, err.Error()
	}
	archive, err := openZipBounded(archivePath, maxZipPeekBytes, maxZipPeekEntries)
	if err != nil {
		return 0, err.Error()
	}
	defer archive.Close()
	var files, encrypted int
	var compressed, uncompressed uint64
	for _, f := range archive.File {
		if err := ctx.Err(); err != nil {
			return 0, "Command cancelled"
		}
		if !isZipDir(f) {
			files++
			compressed += f.CompressedSize64
			uncompressed += f.UncompressedSize64
		}
		if f.Flags&1 != 0 {
			encrypted++
		}
	}
	tree, dirs, err := zipTree(archive.File)
	if err != nil {
		return 0, err.Error()
	}
	info, err := os.Stat(archivePath)
	if err != nil {
		return 0, err.Error()
	}
	return jsonResult(map[string]interface{}{
		"path": archivePath, "name": filepath.Base(archivePath), "archive_size": info.Size(), "entry_count": len(archive.File),
		"file_count": files, "dir_count": dirs, "compressed_size": compressed, "uncompressed_size": uncompressed, "encrypted_count": encrypted,
		"tree": tree, "limits": map[string]interface{}{"archive_bytes": maxZipPeekBytes, "entries": maxZipPeekEntries, "entry_preview_bytes": maxZipEntryBytes},
	})
}

func readRemoteZipEntry(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, err.Error()
	}
	archivePath, err := remoteExisting(s, payloadText(payload["path"]), false)
	if err != nil {
		return 0, err.Error()
	}
	entryName := payloadText(payload["entry_name"])
	if entryName == "" {
		return 0, "entry_name is required"
	}
	archive, err := openZipBounded(archivePath, maxZipPeekBytes, maxZipPeekEntries)
	if err != nil {
		return 0, err.Error()
	}
	defer archive.Close()
	for _, f := range archive.File {
		if f.Name != entryName {
			continue
		}
		normalized, err := safeZipEntry(f.Name)
		if err != nil {
			return 0, err.Error()
		}
		if isZipDir(f) {
			return 0, "ZIP entry is a directory"
		}
		if f.Flags&1 != 0 {
			return 0, "Encrypted ZIP entries cannot be previewed"
		}
		if f.UncompressedSize64 > uint64(maxZipEntryBytes) {
			return 0, "ZIP entry exceeds preview byte limit"
		}
		in, err := f.Open()
		if err != nil {
			return 0, err.Error()
		}
		data, readErr := io.ReadAll(io.LimitReader(&contextReader{ctx: ctx, reader: in}, maxZipEntryBytes+1))
		closeErr := in.Close()
		if readErr != nil {
			return 0, readErr.Error()
		}
		if closeErr != nil {
			return 0, closeErr.Error()
		}
		if len(data) > int(maxZipEntryBytes) {
			return 0, "ZIP entry exceeds preview byte limit"
		}
		text, encoding, err := decodeRemoteText(data)
		result := map[string]interface{}{"path": normalized, "entry_name": f.Name, "name": path.Base(normalized), "size": f.UncompressedSize64}
		if err != nil {
			result["type"] = "binary"
			result["content"] = ""
			result["message"] = "Binary or unsupported text encoding"
		} else {
			result["type"] = "text"
			result["content"] = text
			result["encoding"] = encoding
		}
		return jsonResult(result)
	}
	return 0, "ZIP entry not found"
}

func createRemoteZip(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, err.Error()
	}
	paths, err := pathsForTransfer(s, payload["paths"])
	if err != nil {
		return 0, err.Error()
	}
	dest, err := remoteExisting(s, payloadText(payload["destination_dir"]), true)
	if err != nil {
		return 0, err.Error()
	}
	name := payloadText(payload["archive_name"])
	if name == "" {
		name = "archive.zip"
	}
	name, err = safeTransferFilename(name)
	if err != nil {
		return 0, err.Error()
	}
	if !strings.HasSuffix(strings.ToLower(name), ".zip") {
		name += ".zip"
	}
	target := filepath.Join(dest, name)
	if err := writeZipPaths(ctx, target, paths); err != nil {
		return 0, err.Error()
	}
	info, err := os.Stat(target)
	if err != nil {
		return 0, err.Error()
	}
	return jsonResult(map[string]interface{}{"archive_path": target, "archive_name": name, "source_count": len(paths), "size": info.Size()})
}

// extractRemoteZipEntry preserves the selected item's basename and never overwrites
// an existing target. A selected directory includes only its own subtree.
func extractRemoteZipEntry(ctx context.Context, source, dest, entryName string) (map[string]interface{}, error) {
	requested, err := safeZipEntry(entryName)
	if err != nil || requested == "" {
		return nil, fmt.Errorf("invalid ZIP entry selection")
	}
	archive, err := openZipBounded(source, 1<<63-1, maxZipExtractEntries)
	if err != nil {
		return nil, err
	}
	defer archive.Close()
	normalized := make([]string, len(archive.File))
	var total uint64
	var exactFiles int
	hasDirectory := false
	selected := make([]int, 0)
	for idx, f := range archive.File {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		name, err := safeZipEntry(f.Name)
		if err != nil {
			return nil, err
		}
		if isZipSymlink(f) {
			return nil, fmt.Errorf("ZIP symlink entries are not allowed")
		}
		total += f.UncompressedSize64
		if total > uint64(maxZipExtractBytes) {
			return nil, fmt.Errorf("ZIP exceeds extraction byte limit")
		}
		normalized[idx] = name
		if name == requested {
			selected = append(selected, idx)
			if isZipDir(f) {
				hasDirectory = true
			} else {
				exactFiles++
			}
		} else if strings.HasPrefix(name, requested+"/") {
			selected = append(selected, idx)
			hasDirectory = true
		}
	}
	if exactFiles > 1 || (exactFiles > 0 && hasDirectory) {
		return nil, fmt.Errorf("ambiguous ZIP entry selection")
	}
	isDir := exactFiles == 0 && hasDirectory
	if exactFiles == 0 && !isDir {
		return nil, fmt.Errorf("ZIP entry not found: %s", requested)
	}
	seen := make(map[string]bool)
	for _, idx := range selected {
		if seen[normalized[idx]] {
			return nil, fmt.Errorf("duplicate ZIP entry paths")
		}
		seen[normalized[idx]] = true
	}
	output := filepath.Join(dest, path.Base(requested))
	if _, err := os.Lstat(output); err == nil {
		return nil, fmt.Errorf("ZIP extraction target already exists: %s", output)
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	created := false
	success := false
	defer func() {
		if !success && created {
			if isDir {
				_ = os.RemoveAll(output)
			} else {
				_ = os.Remove(output)
			}
		}
	}()
	var fileCount, dirCount int
	if isDir {
		if err := os.Mkdir(output, 0755); err != nil {
			return nil, err
		}
		created = true
		dirCount = 1
	}
	for _, idx := range selected {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		f := archive.File[idx]
		name := normalized[idx]
		if isDir && name == requested {
			continue
		}
		target := output
		if isDir {
			relative := strings.TrimPrefix(name, requested+"/")
			target = filepath.Join(output, filepath.FromSlash(relative))
			rel, err := filepath.Rel(output, target)
			if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
				return nil, fmt.Errorf("unsafe ZIP extraction path")
			}
		}
		if isZipDir(f) {
			if err := os.MkdirAll(target, 0755); err != nil {
				return nil, err
			}
			dirCount++
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			return nil, err
		}
		reader, err := f.Open()
		if err != nil {
			return nil, err
		}
		writer, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
		if err != nil {
			_ = reader.Close()
			return nil, err
		}
		created = true
		_, copyErr := io.Copy(writer, &contextReader{ctx: ctx, reader: reader})
		closeWriter := writer.Close()
		closeReader := reader.Close()
		if copyErr != nil {
			return nil, copyErr
		}
		if closeWriter != nil {
			return nil, closeWriter
		}
		if closeReader != nil {
			return nil, closeReader
		}
		fileCount++
	}
	success = true
	return map[string]interface{}{
		"archive_path": source, "destination_dir": dest, "extracted_to": output,
		"mode": "selected_entry", "file_count": fileCount, "dir_count": dirCount,
	}, nil
}

func extractRemoteZip(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, err.Error()
	}
	if payloadBool(payload["inspect"]) || payload["conflict_policy"] != nil {
		return extractRemoteZipPolicy(ctx, s, payload)
	}
	source, err := remoteExisting(s, payloadText(payload["path"]), false)
	if err != nil {
		return 0, err.Error()
	}
	dest, err := remoteExisting(s, payloadText(payload["destination_dir"]), true)
	if err != nil {
		return 0, err.Error()
	}
	if entryName := payloadText(payload["entry_name"]); entryName != "" {
		result, err := extractRemoteZipEntry(ctx, source, dest, entryName)
		if err != nil {
			return 0, err.Error()
		}
		return jsonResult(result)
	}
	archive, err := openZipBounded(source, 1<<63-1, maxZipExtractEntries)
	if err != nil {
		return 0, err.Error()
	}
	defer archive.Close()
	var total uint64
	normalized := make([]string, len(archive.File))
	for idx, f := range archive.File {
		if err := ctx.Err(); err != nil {
			return 0, "Command cancelled"
		}
		normalized[idx], err = safeZipEntry(f.Name)
		if err != nil {
			return 0, err.Error()
		}
		if isZipSymlink(f) {
			return 0, "ZIP symlink entries are not allowed"
		}
		total += f.UncompressedSize64
		if total > uint64(maxZipExtractBytes) {
			return 0, "ZIP exceeds extraction byte limit"
		}
	}
	if len(archive.File) == 0 {
		return 0, "ZIP archive is empty"
	}
	rootName := ""
	topNames := make(map[string]bool)
	rootFile := false
	for idx, name := range normalized {
		if name == "" {
			continue
		}
		top := strings.Split(name, "/")[0]
		topNames[top] = true
		if name == top && !isZipDir(archive.File[idx]) {
			rootFile = true
		}
	}
	if len(topNames) == 1 && !rootFile {
		for name := range topNames {
			rootName = name
		}
	}
	extractBase, mode, finalPath := "", "wrapper", ""
	if rootName != "" {
		extractBase = dest
		finalPath = filepath.Join(dest, rootName)
		mode = "single_root"
		if _, err := os.Lstat(finalPath); err == nil {
			return 0, "ZIP extraction target already exists"
		} else if !os.IsNotExist(err) {
			return 0, err.Error()
		}
	} else {
		stem := strings.TrimSuffix(filepath.Base(source), filepath.Ext(source))
		if stem == "" {
			stem = "archive"
		}
		extractBase = filepath.Join(dest, stem)
		for n := 1; ; n++ {
			if _, err := os.Lstat(extractBase); os.IsNotExist(err) {
				break
			} else if err != nil {
				return 0, err.Error()
			}
			extractBase = filepath.Join(dest, fmt.Sprintf("%s_%d", stem, n))
		}
		finalPath = extractBase
	}
	if mode == "wrapper" {
		if err := os.Mkdir(extractBase, 0755); err != nil {
			return 0, err.Error()
		}
	}
	// A single-root archive writes under an as-yet-uncreated root directory.
	cleanup := finalPath
	success := false
	defer func() {
		if !success {
			_ = os.RemoveAll(cleanup)
		}
	}()
	var files, dirs int
	for idx, f := range archive.File {
		if err := ctx.Err(); err != nil {
			return 0, "Command cancelled"
		}
		name := normalized[idx]
		if name == "" {
			continue
		}
		target := filepath.Join(extractBase, filepath.FromSlash(name))
		rel, err := filepath.Rel(extractBase, target)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
			return 0, "unsafe ZIP extraction path"
		}
		if isZipDir(f) {
			if err := os.MkdirAll(target, 0755); err != nil {
				return 0, err.Error()
			}
			dirs++
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			return 0, err.Error()
		}
		input, err := f.Open()
		if err != nil {
			return 0, err.Error()
		}
		output, err := os.OpenFile(target, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0644)
		if err != nil {
			_ = input.Close()
			return 0, err.Error()
		}
		_, copyErr := io.Copy(output, &contextReader{ctx: ctx, reader: input})
		closeOut := output.Close()
		closeIn := input.Close()
		if copyErr != nil {
			return 0, copyErr.Error()
		}
		if closeOut != nil {
			return 0, closeOut.Error()
		}
		if closeIn != nil {
			return 0, closeIn.Error()
		}
		files++
	}
	success = true
	return jsonResult(map[string]interface{}{"archive_path": source, "destination_dir": dest, "extracted_to": finalPath, "mode": mode, "root_name": rootName, "file_count": files, "dir_count": dirs})
}
