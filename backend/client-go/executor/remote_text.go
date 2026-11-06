package executor

import (
	"context"
	"encoding/binary"
	"fmt"
	"os"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

var _ = Register("save_file_content", Usage("save_file_content <payload>"), Help("Save an editable remote text file"), Group("file_path"), CancelPolicy("cooperative"), CommandRunner(saveRemoteText))

const maxEditableRemoteBytes = 2 * 1024 * 1024

func isTextCodepoint(r rune) bool { return r >= 32 || r == '\t' || r == '\n' || r == '\r' || r == '\f' }

func decodeRemoteText(data []byte) (string, string, error) {
	codec := "utf-8"
	switch {
	case len(data) >= 3 && string(data[:3]) == "\xef\xbb\xbf":
		codec = "utf-8-sig"
		data = data[3:]
	case len(data) >= 2 && data[0] == 0xff && data[1] == 0xfe:
		codec = "utf-16-le"
		data = data[2:]
	case len(data) >= 2 && data[0] == 0xfe && data[1] == 0xff:
		codec = "utf-16-be"
		data = data[2:]
	}
	var text string
	if strings.HasPrefix(codec, "utf-16-") {
		if len(data)%2 != 0 {
			return "", "", fmt.Errorf("incomplete UTF-16 data")
		}
		var order binary.ByteOrder = binary.LittleEndian
		if codec == "utf-16-be" {
			order = binary.BigEndian
		}
		units := make([]uint16, len(data)/2)
		for i := range units {
			units[i] = order.Uint16(data[2*i:])
		}
		runes := make([]rune, 0, len(units))
		for i := 0; i < len(units); i++ {
			r := rune(units[i])
			if r >= 0xD800 && r <= 0xDBFF {
				if i+1 >= len(units) || units[i+1] < 0xDC00 || units[i+1] > 0xDFFF {
					return "", "", fmt.Errorf("invalid UTF-16 surrogate")
				}
				r = utf16.DecodeRune(r, rune(units[i+1]))
				i++
			} else if r >= 0xDC00 && r <= 0xDFFF {
				return "", "", fmt.Errorf("invalid UTF-16 surrogate")
			}
			runes = append(runes, r)
		}
		text = string(runes)
	} else {
		if !utf8.Valid(data) {
			return "", "", fmt.Errorf("invalid UTF-8 data")
		}
		text = string(data)
	}
	for _, r := range text {
		if !isTextCodepoint(r) {
			return "", "", fmt.Errorf("binary control characters")
		}
	}
	return text, codec, nil
}

func encodeRemoteText(text, codec string) ([]byte, error) {
	for _, r := range text {
		if !isTextCodepoint(r) {
			return nil, fmt.Errorf("binary control characters")
		}
	}
	switch codec {
	case "utf-8":
		return []byte(text), nil
	case "utf-8-sig":
		return append([]byte{0xef, 0xbb, 0xbf}, []byte(text)...), nil
	case "utf-16-le", "utf-16-be":
		units := utf16.Encode([]rune(text))
		data := make([]byte, 2+len(units)*2)
		data[0], data[1] = 0xff, 0xfe
		var order binary.ByteOrder = binary.LittleEndian
		if codec == "utf-16-be" {
			data[0], data[1] = 0xfe, 0xff
			order = binary.BigEndian
		}
		for i, u := range units {
			order.PutUint16(data[2+i*2:], u)
		}
		return data, nil
	default:
		return nil, fmt.Errorf("unsupported text encoding %q", codec)
	}
}

func saveRemoteText(ctx context.Context, s *Session, raw string, _ func(int, string)) (int, string) {
	payload, err := payloadMap(raw)
	if err != nil {
		return 0, err.Error()
	}
	value, ok := payload["content"].(string)
	if !ok {
		return 0, "content must be text"
	}
	path, err := remoteExisting(s, payloadText(payload["path"]), false)
	if err != nil {
		return 0, err.Error()
	}
	info, err := os.Lstat(path)
	if err != nil {
		return 0, err.Error()
	}
	if !info.Mode().IsRegular() {
		return 0, "file is not regular"
	}
	if info.Size() > maxEditableRemoteBytes {
		return 0, "file exceeds editable preview size limit"
	}
	before, err := os.ReadFile(path)
	if err != nil {
		return 0, err.Error()
	}
	_, actual, err := decodeRemoteText(before)
	if err != nil {
		return 0, "File encoding is unknown; editing is disabled"
	}
	requested := payloadText(payload["encoding"])
	if requested == "" {
		requested = "utf-8"
	}
	if actual != requested {
		return 0, "File encoding changed or does not match the preview"
	}
	output, err := encodeRemoteText(value, actual)
	if err != nil {
		return 0, err.Error()
	}
	if err := ctx.Err(); err != nil {
		return 0, "Command cancelled"
	}
	// Existing path only, no implicit create: mirrors Python's save_file_content.
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_TRUNC, 0)
	if err != nil {
		return 0, err.Error()
	}
	if _, err = file.Write(output); err != nil {
		_ = file.Close()
		return 0, err.Error()
	}
	if err = file.Close(); err != nil {
		return 0, err.Error()
	}
	return 1, fmt.Sprintf("File saved successfully\nPath: %s\nSize: %d bytes\nEncoding: %s", path, len(output), actual)
}
