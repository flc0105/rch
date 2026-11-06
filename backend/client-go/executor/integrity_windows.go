//go:build windows

package executor

import (
	"runtime"
	"syscall"
	"unsafe"
)

const (
	tokenQuery          = 0x0008
	tokenIntegrityLevel = 25
)

var (
	integrityAdvapi32         = syscall.NewLazyDLL("advapi32.dll")
	integrityOpenProcessToken = integrityAdvapi32.NewProc("OpenProcessToken")
	integrityGetTokenInfo     = integrityAdvapi32.NewProc("GetTokenInformation")
	integrityGetSidSubCount   = integrityAdvapi32.NewProc("GetSidSubAuthorityCount")
	integrityGetSidSub        = integrityAdvapi32.NewProc("GetSidSubAuthority")
	integrityKernel32         = syscall.NewLazyDLL("kernel32.dll")
	integrityGetCurrentProc   = integrityKernel32.NewProc("GetCurrentProcess")
)

func detectIntegrity() string {
	process, _, _ := integrityGetCurrentProc.Call()
	var token syscall.Handle
	ok, _, _ := integrityOpenProcessToken.Call(process, tokenQuery, uintptr(unsafe.Pointer(&token)))
	if ok == 0 {
		return "Unknown"
	}
	defer syscall.CloseHandle(token)

	var required uint32
	integrityGetTokenInfo.Call(uintptr(token), tokenIntegrityLevel, 0, 0, uintptr(unsafe.Pointer(&required)))
	if required < uint32(unsafe.Sizeof(uintptr(0))) || required > 65536 {
		return "Unknown"
	}
	data := make([]byte, required)
	ok, _, _ = integrityGetTokenInfo.Call(uintptr(token), tokenIntegrityLevel,
		uintptr(unsafe.Pointer(&data[0])), uintptr(required), uintptr(unsafe.Pointer(&required)))
	if ok == 0 {
		return "Unknown"
	}
	// TOKEN_MANDATORY_LABEL starts with SID_AND_ATTRIBUTES; its first pointer is the SID.
	sid := *(*uintptr)(unsafe.Pointer(&data[0]))
	if sid == 0 {
		return "Unknown"
	}
	countPtr, _, _ := integrityGetSidSubCount.Call(sid)
	if countPtr == 0 {
		return "Unknown"
	}
	count := *(*byte)(unsafe.Pointer(countPtr))
	if count == 0 {
		return "Unknown"
	}
	ridPtr, _, _ := integrityGetSidSub.Call(sid, uintptr(count-1))
	if ridPtr == 0 {
		return "Unknown"
	}
	rid := *(*uint32)(unsafe.Pointer(ridPtr))
	runtime.KeepAlive(data) // SID points into the token information buffer.
	return integrityLabelFromRID(rid)
}
