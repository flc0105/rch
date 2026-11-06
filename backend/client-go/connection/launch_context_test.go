package connection

import "testing"

func TestLaunchClassificationCanonicalModes(t *testing.T) {
	cases := []struct {
		name  string
		facts launchFacts
		want  launchContext
	}{
		{"shell foreground", launchFacts{platform: "linux", directParent: "bash", interactive: true}, launchContext{"terminal", "bash"}},
		{"shell background", launchFacts{platform: "linux", directParent: "zsh", interactive: true, background: true}, launchContext{"terminal_background", "zsh"}},
		{"nohup redirected", launchFacts{platform: "linux", directParent: "bash", interactive: false}, launchContext{"terminal_background", "bash"}},
		{"mac login shell foreground", launchFacts{platform: "darwin", directParent: "-zsh", interactive: true}, launchContext{"terminal", "zsh"}},
		{"mac login shell background with tty", launchFacts{platform: "darwin", directParent: "-zsh", interactive: true, background: true}, launchContext{"terminal_background", "zsh"}},
		{"mac login shell nohup fully redirected", launchFacts{platform: "darwin", directParent: "/bin/-zsh", interactive: false, background: true}, launchContext{"terminal_background", "zsh"}},
		{"mac login shell nohup with tty", launchFacts{platform: "darwin", directParent: "/bin/zsh", interactive: true, background: true}, launchContext{"terminal_background", "zsh"}},
		{"new session before ide", launchFacts{platform: "darwin", directParent: "pycharm", ancestors: []string{"pycharm"}, newSession: true}, launchContext{"detached", "new_session"}},
		{"verified launch agent", launchFacts{platform: "darwin", managed: launchContext{"user_service", "launchagent"}, newSession: true}, launchContext{"user_service", "launchagent"}},
		{"verified launch daemon", launchFacts{platform: "darwin", managed: launchContext{"system_service", "launchdaemon"}}, launchContext{"system_service", "launchdaemon"}},
		{"verified systemd", launchFacts{platform: "linux", managed: launchContext{"system_service", "systemd"}, newSession: true}, launchContext{"system_service", "systemd"}},
		{"systemd user", launchFacts{platform: "linux", managed: launchContext{"user_service", "systemd_user"}}, launchContext{"user_service", "systemd_user"}},
		{"cron", launchFacts{platform: "linux", managed: launchContext{"scheduled", "cron"}}, launchContext{"scheduled", "cron"}},
		{"scheduler", launchFacts{platform: "windows", managed: launchContext{"scheduled", "schtasks"}}, launchContext{"scheduled", "schtasks"}},
		{"windows service", launchFacts{platform: "windows", managed: launchContext{"system_service", "windows_service"}}, launchContext{"system_service", "windows_service"}},
		{"windows shell", launchFacts{platform: "windows", directParent: `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`, interactive: true}, launchContext{"terminal", "powershell"}},
		{"windows shell detached", launchFacts{platform: "windows", directParent: "cmd.exe"}, launchContext{"detached", "detached_process"}},
		{"windows no console", launchFacts{platform: "windows"}, launchContext{"detached", "detached_process"}},
		{"ide ancestry is not a Go launch mode", launchFacts{platform: "linux", ancestors: []string{"/Applications/PyCharm.app"}}, launchContext{"unknown", ""}},
		{"pycharm parent with no tty", launchFacts{platform: "darwin", directParent: "/Applications/PyCharm.app", ancestors: []string{"pycharm"}, noTerminal: true}, launchContext{"detached", ""}},
		{"darwin without tty", launchFacts{platform: "darwin", noTerminal: true}, launchContext{"detached", ""}},
		{"unknown launcher", launchFacts{platform: "linux"}, launchContext{"unknown", ""}},
	}
	// An IDE environment inherited from a parent must not reclassify Go.
	t.Setenv("PYCHARM_HOSTED", "1")
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := classifyLaunch(tc.facts); got != tc.want {
				t.Fatalf("got %+v, want %+v", got, tc.want)
			}
		})
	}
}

func TestCronOnlyWithActualAncestor(t *testing.T) {
	if !cronAncestor([]string{"/usr/sbin/cron", "sh -c launch-client"}) || !cronAncestor([]string{"crond"}) {
		t.Fatal("cron supervisor not detected")
	}
	if cronAncestor([]string{"curl https://example.com/cronwatch", "some-chronology"}) {
		t.Fatal("cron substring produced a false positive")
	}
}

func TestDetectedLaunchContextHasCanonicalMode(t *testing.T) {
	c := detectLaunchContext()
	valid := map[string]bool{
		"terminal": true, "terminal_background": true, "detached": true,
		"user_service": true, "system_service": true, "scheduled": true, "unknown": true,
	}
	if !valid[c.mode] {
		t.Fatalf("non-canonical launch mode %q, source %q", c.mode, c.source)
	}
}
