package config

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
)

// Runtime settings are kept separate from build-time networking constants.
// Only values different from defaults are written to disk.
type runtimeOption struct {
	Default     interface{}
	Group       string
	Description string
	Min         int
	Max         int // Zero means no upper bound for integer settings.
	Choices     []string
}

const (
	ReconnectBackoffMinConfig  = "RECONNECT_BACKOFF_MIN_SECONDS"
	ReconnectBackoffMaxConfig  = "RECONNECT_BACKOFF_MAX_SECONDS"
	backoffSecondsLimit        = 2147483647
	ServerInboundTimeoutConfig = "SERVER_INBOUND_TIMEOUT_SECONDS"
	TransferModeConfig         = "FILE_TRANSFER_MODE"
	TransferBufferConfig       = "HTTP_TRANSFER_BUFFER_SIZE"
	TransferHTTPStreaming      = "http_streaming"
	TransferTCPStreaming       = "tcp_streaming"
	ScriptExecutionConfig      = "SCRIPT_DEFAULT_EXECUTION_MODE"
	ScriptOutputConfig         = "SCRIPT_DEFAULT_OUTPUT_MODE"
	ScriptSubprocessPipe       = "subprocess_pipe"
	ScriptCollect              = "collect"
	ScriptStream               = "stream"
)

var runtimeOptions = map[string]runtimeOption{
	ReconnectBackoffMinConfig:        {5, "connection", "Initial reconnect delay in seconds.", 1, backoffSecondsLimit, nil},
	ReconnectBackoffMaxConfig:        {30, "connection", "Maximum reconnect delay in seconds.", 1, backoffSecondsLimit, nil},
	ServerInboundTimeoutConfig:       {120, "connection", "Seconds without an inbound Server message before reconnecting; 0 disables this timeout.", 0, 0, nil},
	TransferModeConfig:               {TransferHTTPStreaming, "transfer", "File transfer mode.", 0, 0, []string{TransferHTTPStreaming, TransferTCPStreaming}},
	TransferBufferConfig:             {1048576, "transfer", "Shared file transfer buffer size in bytes.", 65536, 16777216, nil},
	ScriptExecutionConfig:            {ScriptSubprocessPipe, "script", "Script default execution mode (external Python only).", 0, 0, []string{ScriptSubprocessPipe}},
	ScriptOutputConfig:               {ScriptCollect, "script", "Script default output mode.", 0, 0, []string{ScriptCollect, ScriptStream}},
	"COMMAND_DEFAULT_SHELL_TIMEOUT":  {30, "command", "Default timeout for shell command execution (seconds).", 1, 86400, nil},
	"COMMAND_DEFAULT_STREAM_TIMEOUT": {300, "command", "Default timeout for streamed shell execution (seconds).", 1, 86400, nil},
	"SCRIPT_DEFAULT_TIMEOUT":         {300, "script", "Default timeout for external Python scripts (seconds).", 1, 86400, nil},
	"SCRIPT_PYTHON_PATH":             {"", "script", "External Python interpreter path. Empty uses the system PATH.", 0, 0, nil},
}

type RuntimeStore struct {
	mu        sync.RWMutex
	path      string
	overrides map[string]interface{}
	loadErr   error
}

func NewRuntimeStore(path string) *RuntimeStore {
	store := &RuntimeStore{path: path, overrides: make(map[string]interface{})}
	data, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return store
	}
	if err != nil {
		store.loadErr = err
		return store
	}
	var values map[string]interface{}
	if err = json.Unmarshal(data, &values); err != nil {
		store.loadErr = fmt.Errorf("read runtime config: %w", err)
		return store
	}
	var backoffErr error
	for key, value := range values {
		if key == "_meta" {
			continue
		}
		opt, valid := runtimeOptions[key]
		if !valid {
			continue
		}
		normalized, err := checkValue(key, value, opt)
		if err != nil {
			if key == ReconnectBackoffMinConfig || key == ReconnectBackoffMaxConfig {
				backoffErr = err
				continue
			}
			store.overrides = make(map[string]interface{})
			store.loadErr = fmt.Errorf("runtime config %s: %w", key, err)
			return store
		}
		if normalized != opt.Default {
			store.overrides[key] = normalized
		}
	}
	if backoffErr == nil {
		backoffErr = validateReconnectBackoff(store.overrides)
	}
	if backoffErr != nil {
		log.Printf("Invalid reconnect backoff configuration: %v; using defaults", backoffErr)
		delete(store.overrides, ReconnectBackoffMinConfig)
		delete(store.overrides, ReconnectBackoffMaxConfig)
	}
	return store
}

func RuntimeConfigPath() string {
	base, err := os.UserConfigDir()
	if err != nil {
		return filepath.Join(".", "rchclient", "runtime_config_go.json")
	}
	return filepath.Join(base, "rchclient", "runtime_config_go.json")
}

var activeRuntimeStore = NewRuntimeStore(RuntimeConfigPath())

func Runtime() *RuntimeStore { return activeRuntimeStore }

func runtimeValue(overrides map[string]interface{}, key string) interface{} {
	if v, ok := overrides[key]; ok {
		return v
	}
	return runtimeOptions[key].Default
}

func (s *RuntimeStore) Get(key string) interface{} {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return runtimeValue(s.overrides, key)
}

func reconnectBackoffBounds(overrides map[string]interface{}) (int, int) {
	return runtimeValue(overrides, ReconnectBackoffMinConfig).(int), runtimeValue(overrides, ReconnectBackoffMaxConfig).(int)
}

func (s *RuntimeStore) ReconnectBackoffBounds() (int, int) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return reconnectBackoffBounds(s.overrides)
}

func validateReconnectBackoff(overrides map[string]interface{}) error {
	minimum, maximum := reconnectBackoffBounds(overrides)
	if minimum > maximum {
		return fmt.Errorf("%s must be <= %s", ReconnectBackoffMinConfig, ReconnectBackoffMaxConfig)
	}
	return nil
}

func (s *RuntimeStore) Seconds(key string) int   { return s.Get(key).(int) }
func (s *RuntimeStore) PythonPath() string       { return s.Get("SCRIPT_PYTHON_PATH").(string) }
func (s *RuntimeStore) FileTransferMode() string { return s.Get(TransferModeConfig).(string) }
func (s *RuntimeStore) TransferBufferSize() int  { return s.Seconds(TransferBufferConfig) }

func checkValue(key string, value interface{}, opt runtimeOption) (interface{}, error) {
	switch opt.Default.(type) {
	case int:
		number, ok := value.(float64)
		if !ok {
			if n, valid := value.(int); valid {
				number = float64(n)
				ok = true
			}
		}
		if !ok || number != float64(int(number)) || int(number) < opt.Min || (opt.Max > 0 && int(number) > opt.Max) {
			if opt.Max == 0 {
				return nil, fmt.Errorf("%s must be an integer >= %d", key, opt.Min)
			}
			return nil, fmt.Errorf("%s must be an integer from %d to %d", key, opt.Min, opt.Max)
		}
		return int(number), nil
	case string:
		text, ok := value.(string)
		if !ok {
			return nil, fmt.Errorf("%s must be a string", key)
		}
		text = strings.TrimSpace(text)
		if len(opt.Choices) > 0 {
			for _, choice := range opt.Choices {
				if text == choice {
					return text, nil
				}
			}
			return nil, fmt.Errorf("%s must be one of %v", key, opt.Choices)
		}
		return text, nil
	}
	return nil, fmt.Errorf("unsupported option %s", key)
}

func (s *RuntimeStore) Set(key, raw string) (string, error) {
	key = strings.ToUpper(strings.TrimSpace(key))
	opt, ok := runtimeOptions[key]
	if !ok {
		return "", fmt.Errorf("unknown runtime config key: %s", key)
	}
	var value interface{} = raw
	if _, isInt := opt.Default.(int); isInt {
		var n int
		if _, err := fmt.Sscanf(raw, "%d", &n); err != nil || fmt.Sprint(n) != strings.TrimSpace(raw) {
			return "", fmt.Errorf("%s must be an integer", key)
		}
		value = n
	}
	return s.SetValue(key, value)
}

// SetValue is the structured configuration boundary, shared with CLI Set.
func (s *RuntimeStore) SetValue(key string, value interface{}) (string, error) {
	key = strings.ToUpper(strings.TrimSpace(key))
	opt, ok := runtimeOptions[key]
	if !ok {
		return "", fmt.Errorf("unknown runtime config key: %s", key)
	}
	normalized, err := checkValue(key, value, opt)
	if err != nil {
		return "", err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.loadErr != nil {
		return "", s.loadErr
	}
	next := cloneOverrides(s.overrides)
	if normalized == opt.Default {
		delete(next, key)
	} else {
		next[key] = normalized
	}
	if err := validateReconnectBackoff(next); err != nil {
		return "", err
	}
	if err := s.persist(next); err != nil {
		return "", err
	}
	s.overrides = next
	if normalized == opt.Default {
		return "default", nil
	}
	return "override", nil
}

func (s *RuntimeStore) Reset(key string) error {
	key = strings.ToUpper(strings.TrimSpace(key))
	if _, ok := runtimeOptions[key]; !ok {
		return fmt.Errorf("unknown runtime config key: %s", key)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.loadErr != nil {
		return s.loadErr
	}
	next := cloneOverrides(s.overrides)
	delete(next, key)
	if err := validateReconnectBackoff(next); err != nil {
		return err
	}
	if err := s.persist(next); err != nil {
		return err
	}
	s.overrides = next
	return nil
}

func (s *RuntimeStore) ResetAll() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.loadErr != nil {
		return s.loadErr
	}
	next := map[string]interface{}{}
	if err := validateReconnectBackoff(next); err != nil {
		return err
	}
	if err := s.persist(next); err != nil {
		return err
	}
	s.overrides = next
	return nil
}

func cloneOverrides(source map[string]interface{}) map[string]interface{} {
	next := make(map[string]interface{}, len(source))
	for key, value := range source {
		next[key] = value
	}
	return next
}

func (s *RuntimeStore) persist(values map[string]interface{}) error {
	if len(values) == 0 {
		if err := os.Remove(s.path); err != nil && !os.IsNotExist(err) {
			return err
		}
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(s.path), 0700); err != nil {
		return err
	}
	content, err := json.MarshalIndent(values, "", "  ")
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(filepath.Dir(s.path), ".rch-go-runtime-*")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	if err := file.Chmod(0600); err != nil {
		file.Close()
		return err
	}
	if _, err := file.Write(append(content, '\n')); err != nil {
		file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	return os.Rename(file.Name(), s.path)
}

func (s *RuntimeStore) Payload() map[string]interface{} {
	s.mu.RLock()
	defer s.mu.RUnlock()
	keys := make([]string, 0, len(runtimeOptions))
	for key := range runtimeOptions {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	items := make([]map[string]interface{}, 0, len(keys))
	for _, key := range keys {
		opt := runtimeOptions[key]
		current, source := opt.Default, "default"
		if value, ok := s.overrides[key]; ok {
			current, source = value, "override"
		}
		kind := "string"
		if _, ok := opt.Default.(int); ok {
			kind = "integer"
		}
		var min, max interface{}
		if kind == "integer" {
			min = opt.Min
			if opt.Max > 0 {
				max = opt.Max
			}
		}
		items = append(items, map[string]interface{}{
			"key": key, "value": current, "default_value": opt.Default,
			"source": source, "group": opt.Group, "desc": opt.Description,
			"value_type": kind, "choices": append([]string{}, opt.Choices...), "min_value": min,
			"max_value": max, "step": nil, "editable": true,
		})
	}
	return map[string]interface{}{"store_path": s.path, "items": items}
}

func (s *RuntimeStore) LoadError() error { return s.loadErr }
