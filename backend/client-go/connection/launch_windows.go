//go:build windows

package connection

import (
	"os"
	"strings"
	"syscall"
	"unsafe"
)

const (
	th32csSnapProcess  = 0x00000002
	scManagerEnumerate = 0x0004
	serviceWin32       = 0x00000030
	serviceStateAll    = 0x00000003
	serviceRunning     = 0x00000004
	scEnumProcessInfo  = 0
)

var (
	launchKernel32  = syscall.NewLazyDLL("kernel32.dll")
	launchAdvapi32  = syscall.NewLazyDLL("advapi32.dll")
	procSnapshot    = launchKernel32.NewProc("CreateToolhelp32Snapshot")
	procFirst       = launchKernel32.NewProc("Process32FirstW")
	procNext        = launchKernel32.NewProc("Process32NextW")
	procConsole     = launchKernel32.NewProc("GetConsoleProcessList")
	procStdHandle   = launchKernel32.NewProc("GetStdHandle")
	procConsoleMode = launchKernel32.NewProc("GetConsoleMode")
	procOpenSCM     = launchAdvapi32.NewProc("OpenSCManagerW")
	procEnumSCM     = launchAdvapi32.NewProc("EnumServicesStatusExW")
	procCloseSCM    = launchAdvapi32.NewProc("CloseServiceHandle")
	procStrLenW     = launchKernel32.NewProc("lstrlenW")
)

type winProcessEntry struct {
	size, usage, pid      uint32
	defaultHeap           uintptr
	module, threads, ppid uint32
	priority              int32
	flags                 uint32
	exe                   [260]uint16
}

type winProcess struct {
	pid, ppid int
	name      string
}

func windowsProcessTree() map[int]winProcess {
	result := map[int]winProcess{}
	handle, _, _ := procSnapshot.Call(th32csSnapProcess, 0)
	if handle == 0 || handle == ^uintptr(0) {
		return result
	}
	defer syscall.CloseHandle(syscall.Handle(handle))
	entry := winProcessEntry{size: uint32(unsafe.Sizeof(winProcessEntry{}))}
	ok, _, _ := procFirst.Call(handle, uintptr(unsafe.Pointer(&entry)))
	for ok != 0 {
		result[int(entry.pid)] = winProcess{int(entry.pid), int(entry.ppid), strings.ToLower(syscall.UTF16ToString(entry.exe[:]))}
		entry.size = uint32(unsafe.Sizeof(winProcessEntry{}))
		ok, _, _ = procNext.Call(handle, uintptr(unsafe.Pointer(&entry)))
	}
	return result
}

type winServiceStatus struct {
	serviceType, currentState, controlsAccepted, win32ExitCode, serviceExitCode, checkpoint, waitHint, pid, flags uint32
}

type winServiceEntry struct {
	name, displayName *uint16
	status            winServiceStatus
}

type winService struct {
	name    string
	pid     int
	running bool
}

func winUTF16PtrString(ptr *uint16) string {
	if ptr == nil {
		return ""
	}
	n, _, _ := procStrLenW.Call(uintptr(unsafe.Pointer(ptr)))
	if n > 32767 {
		return ""
	}
	return syscall.UTF16ToString(unsafe.Slice(ptr, int(n)))
}

func windowsServices() []winService {
	handle, _, _ := procOpenSCM.Call(0, 0, scManagerEnumerate)
	if handle == 0 {
		return nil
	}
	defer procCloseSCM.Call(handle)
	services := []winService{}
	buffer := make([]byte, 64*1024)
	var resume uint32
	for i := 0; i < 32; i++ {
		var needed, count uint32
		ok, _, callErr := procEnumSCM.Call(handle, scEnumProcessInfo, serviceWin32, serviceStateAll,
			uintptr(unsafe.Pointer(&buffer[0])), uintptr(len(buffer)),
			uintptr(unsafe.Pointer(&needed)), uintptr(unsafe.Pointer(&count)), uintptr(unsafe.Pointer(&resume)), 0)
		if count > 0 && uintptr(count)*unsafe.Sizeof(winServiceEntry{}) <= uintptr(len(buffer)) {
			entries := unsafe.Slice((*winServiceEntry)(unsafe.Pointer(&buffer[0])), count)
			for _, item := range entries {
				services = append(services, winService{
					name: winUTF16PtrString(item.name), pid: int(item.status.pid),
					running: item.status.currentState == serviceRunning,
				})
			}
		}
		if ok != 0 {
			break
		}
		if callErr != syscall.ERROR_MORE_DATA {
			break
		}
		if needed > uint32(len(buffer)) {
			if needed > 4*1024*1024 {
				break
			}
			buffer = make([]byte, needed)
		}
	}
	return services
}

func windowsInteractiveConsole() bool {
	var pid uint32
	n, _, _ := procConsole.Call(uintptr(unsafe.Pointer(&pid)), 1)
	if n == 0 {
		return false
	}
	for _, id := range []int32{-10, -11, -12} {
		handle, _, _ := procStdHandle.Call(uintptr(uint32(id)))
		if handle == 0 || handle == ^uintptr(0) {
			continue
		}
		var mode uint32
		ok, _, _ := procConsoleMode.Call(handle, uintptr(unsafe.Pointer(&mode)))
		if ok != 0 {
			return true
		}
	}
	return false
}

func detectLaunchContext() launchContext {
	pid := os.Getpid()
	processes := windowsProcessTree()
	ancestors := make([]string, 0, 8)
	direct := ""
	seen := map[int]bool{pid: true}
	parentID := processes[pid].ppid
	parentPIDs := make(map[int]bool)
	for len(ancestors) < 32 && parentID > 0 && !seen[parentID] {
		seen[parentID], parentPIDs[parentID] = true, true
		parent, exists := processes[parentID]
		if !exists {
			break
		}
		if direct == "" {
			direct = parent.name
		}
		ancestors = append(ancestors, parent.name)
		parentID = parent.ppid
	}
	services := windowsServices()
	managed := launchContext{}
	for _, svc := range services {
		if svc.running && svc.pid == pid {
			managed = launchContext{"system_service", "windows_service"}
			break
		}
	}
	if managed.mode == "" {
		if ancestorHas(ancestors, "taskeng.exe", "taskhostw.exe", "schtasks.exe") {
			managed = launchContext{"scheduled", "schtasks"}
		} else {
			for _, svc := range services {
				if svc.running && strings.EqualFold(svc.name, "Schedule") && parentPIDs[svc.pid] {
					managed = launchContext{"scheduled", "schtasks"}
					break
				}
			}
		}
	}
	return classifyLaunch(launchFacts{
		platform: "windows", managed: managed, directParent: direct, ancestors: ancestors,
		interactive: windowsInteractiveConsole(),
	})
}
