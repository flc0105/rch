package connection

import (
	"path/filepath"
	"strings"
)

type launchContext struct {
	mode   string
	source string
}

type launchFacts struct {
	platform     string
	managed      launchContext
	directParent string
	ancestors    []string
	interactive  bool
	background   bool
	newSession   bool
	noTerminal   bool
}

var shellLaunchSources = map[string]string{
	"zsh": "zsh", "bash": "bash", "sh": "sh", "dash": "dash",
	"fish": "fish", "ksh": "ksh", "tcsh": "tcsh",
	"cmd.exe": "cmd", "powershell.exe": "powershell", "pwsh.exe": "pwsh",
}

func classifyLaunch(f launchFacts) launchContext {
	if f.managed.mode != "" {
		return f.managed
	}
	if f.platform != "windows" && f.newSession && !f.interactive {
		return launchContext{"detached", "new_session"}
	}
	parent := strings.TrimPrefix(strings.ToLower(filepath.Base(strings.ReplaceAll(strings.TrimSpace(f.directParent), `\`, "/"))), "-")
	if source := shellLaunchSources[parent]; source != "" {
		if f.platform == "windows" && !f.interactive {
			return launchContext{"detached", "detached_process"}
		}
		if f.background || !f.interactive {
			return launchContext{"terminal_background", source}
		}
		return launchContext{"terminal", source}
	}
	if f.interactive {
		return launchContext{"terminal", ""}
	}
	if f.platform == "windows" {
		return launchContext{"detached", "detached_process"}
	}
	if f.platform == "darwin" && f.noTerminal {
		return launchContext{"detached", ""}
	}
	return launchContext{"unknown", ""}
}

func ancestorHas(ancestors []string, tokens ...string) bool {
	for _, ancestor := range ancestors {
		lower := strings.ToLower(ancestor)
		for _, token := range tokens {
			if strings.Contains(lower, token) {
				return true
			}
		}
	}
	return false
}

func cronAncestor(ancestors []string) bool {
	for _, value := range ancestors {
		for _, part := range strings.FieldsFunc(strings.ToLower(value), func(r rune) bool {
			return r == ' ' || r == '/' || r == '\\' || r == '\x00'
		}) {
			if part == "cron" || part == "crond" {
				return true
			}
		}
	}
	return false
}
