//go:build !linux && !darwin && !windows

package connection

func detectLaunchContext() launchContext { return launchContext{"unknown", ""} }
