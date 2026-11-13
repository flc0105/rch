package executor

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
)

func remotePayload(raw string) (interface{}, error) {
	raw = strings.TrimSpace(raw)
	if !strings.HasPrefix(raw, "__json__:") {
		return raw, nil
	}
	encoded := strings.TrimPrefix(raw, "__json__:")
	data, err := base64.URLEncoding.DecodeString(encoded)
	if err != nil {
		return nil, fmt.Errorf("invalid structured argument: %w", err)
	}
	var payload interface{}
	if err := json.Unmarshal(data, &payload); err != nil {
		return nil, fmt.Errorf("invalid structured JSON: %w", err)
	}
	return payload, nil
}

func payloadMap(raw string) (map[string]interface{}, error) {
	value, err := remotePayload(raw)
	if err != nil {
		return nil, err
	}
	payload, ok := value.(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("expected structured JSON object")
	}
	return payload, nil
}

func jsonResult(value interface{}) (int, string) {
	data, err := json.Marshal(value)
	if err != nil {
		return 0, fmt.Sprintf("Failed to encode result: %v", err)
	}
	return 1, string(data)
}
