package main

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"runtime"
	"strconv"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

var (
	winHTTP          = syscall.NewLazyDLL("winhttp.dll")
	httpOpen         = winHTTP.NewProc("WinHttpOpen")
	httpConnect      = winHTTP.NewProc("WinHttpConnect")
	httpOpenRequest  = winHTTP.NewProc("WinHttpOpenRequest")
	httpSetOption    = winHTTP.NewProc("WinHttpSetOption")
	httpSetCallback  = winHTTP.NewProc("WinHttpSetStatusCallback")
	httpSendRequest  = winHTTP.NewProc("WinHttpSendRequest")
	httpReceive      = winHTTP.NewProc("WinHttpReceiveResponse")
	httpQueryHeaders = winHTTP.NewProc("WinHttpQueryHeaders")
	httpReadData     = winHTTP.NewProc("WinHttpReadData")
	httpCloseHandle  = winHTTP.NewProc("WinHttpCloseHandle")
)

type localHTTP struct{ session uintptr }

const (
	httpHandleClosing = 0x00000800
	httpHeadersReady  = 0x00020000
	httpReadComplete  = 0x00080000
	httpRequestError  = 0x00200000
	httpSendComplete  = 0x00400000
)

type httpCompletion struct {
	status, bytes uint32
	err           error
}
type httpRequestState struct {
	events chan httpCompletion
	closed chan struct{}
}

var httpRequests = struct {
	sync.Mutex
	next uintptr
	live map[uintptr]*httpRequestState
}{live: make(map[uintptr]*httpRequestState)}

var httpCallback = syscall.NewCallback(func(_ uintptr, id uintptr, status uint32, info unsafe.Pointer, length uint32) uintptr {
	httpRequests.Lock()
	state := httpRequests.live[id]
	httpRequests.Unlock()
	if state == nil {
		return 0
	}
	if status == httpHandleClosing {
		close(state.closed)
		return 0
	}
	event := httpCompletion{status: status, bytes: length}
	if status == httpRequestError {
		result := (*struct {
			Operation uintptr
			Code      uint32
		})(info)
		event.err = syscall.Errno(result.Code)
	}
	// Only completion/error notifications are subscribed. No request has more
	// than one outstanding operation; callbacks never perform another operation.
	state.events <- event
	return 0
})

func (s *httpRequestState) wait(ctx context.Context, expected uint32) (uint32, error) {
	select {
	case event := <-s.events:
		if event.err != nil {
			return 0, event.err
		}
		if event.status != expected {
			return 0, fmt.Errorf("unexpected WinHTTP completion: %x", event.status)
		}
		return event.bytes, ctx.Err()
	case <-ctx.Done():
		return 0, ctx.Err()
	}
}

func newLocalHTTP() (*localHTTP, error) {
	// WINHTTP_ACCESS_TYPE_NO_PROXY; system HTTP is used only for fixed loopback
	// ExtUI origins, without a bundled HTTP/TLS stack or browser runtime.
	// WINHTTP_FLAG_ASYNC lets cancellation close a pending request safely.
	h, _, err := httpOpen.Call(uintptr(unsafe.Pointer(wide("BomanaBasic"))), 1, 0, 0, 0x10000000)
	if h == 0 {
		return nil, fmt.Errorf("WinHttpOpen: %w", err)
	}
	return &localHTTP{session: h}, nil
}

// The sampling owner closes the session only after its request goroutines join.
func (c *localHTTP) close() { httpCloseHandle.Call(c.session) }

func (c *localHTTP) read(ctx context.Context, endpoint *url.URL, maxBytes int64) ([]byte, string, error) {
	if err := ctx.Err(); err != nil {
		return nil, "", err
	}
	ctx, cancel := context.WithTimeout(ctx, 600*time.Millisecond)
	defer cancel()
	port, err := strconv.ParseUint(endpoint.Port(), 10, 16)
	if err != nil {
		return nil, "", err
	}
	connection, _, err := httpConnect.Call(c.session, uintptr(unsafe.Pointer(wide(endpoint.Hostname()))), uintptr(port), 0)
	if connection == 0 {
		return nil, "", fmt.Errorf("WinHttpConnect: %w", err)
	}
	defer httpCloseHandle.Call(connection)
	request, _, err := httpOpenRequest.Call(connection, uintptr(unsafe.Pointer(wide("GET"))), uintptr(unsafe.Pointer(wide(endpoint.RequestURI()))), 0, 0, 0, 0)
	if request == 0 {
		return nil, "", fmt.Errorf("WinHttpOpenRequest: %w", err)
	}
	state := &httpRequestState{events: make(chan httpCompletion, 4), closed: make(chan struct{})}
	httpRequests.Lock()
	httpRequests.next++
	id := httpRequests.next
	httpRequests.live[id] = state
	httpRequests.Unlock()
	subscribed := false
	var pin runtime.Pinner
	defer func() {
		httpCloseHandle.Call(request)
		if subscribed {
			// Closing cancels pending async work. The last callback is the lifetime
			// boundary for the pinned read buffer and callback context.
			<-state.closed
		}
		pin.Unpin()
		httpRequests.Lock()
		delete(httpRequests.live, id)
		httpRequests.Unlock()
	}()
	if ok, _, err := httpSetOption.Call(request, 45, uintptr(unsafe.Pointer(&id)), unsafe.Sizeof(id)); ok == 0 {
		return nil, "", fmt.Errorf("WinHTTP request context: %w", err)
	}
	flags := uintptr(httpHandleClosing | httpHeadersReady | httpReadComplete | httpRequestError | httpSendComplete)
	if previous, _, err := httpSetCallback.Call(request, httpCallback, flags, 0); previous == ^uintptr(0) {
		return nil, "", fmt.Errorf("WinHttpSetStatusCallback: %w", err)
	}
	subscribed = true
	// WINHTTP_OPTION_DISABLE_FEATURE: cookies, redirects, automatic auth.
	disabled := uint32(1 | 2 | 4)
	if ok, _, err := httpSetOption.Call(request, 63, uintptr(unsafe.Pointer(&disabled)), 4); ok == 0 {
		return nil, "", fmt.Errorf("WinHttpSetOption: %w", err)
	}
	if ok, _, err := httpSendRequest.Call(request, 0, 0, 0, 0, 0, id); ok == 0 {
		return nil, "", fmt.Errorf("WinHttpSendRequest: %w", err)
	}
	if _, err := state.wait(ctx, httpSendComplete); err != nil {
		return nil, "", err
	}
	if ok, _, err := httpReceive.Call(request, 0); ok == 0 {
		return nil, "", fmt.Errorf("WinHttpReceiveResponse: %w", err)
	}
	if _, err := state.wait(ctx, httpHeadersReady); err != nil {
		return nil, "", err
	}
	var status uint32
	statusBytes := uint32(4)
	// WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER.
	if ok, _, err := httpQueryHeaders.Call(request, 19|0x20000000, 0, uintptr(unsafe.Pointer(&status)), uintptr(unsafe.Pointer(&statusBytes)), 0); ok == 0 {
		return nil, "", fmt.Errorf("WinHttpQueryHeaders: %w", err)
	}
	if status != 200 {
		return nil, "", fmt.Errorf("%s returned HTTP %d", endpoint.Path, status)
	}
	var declared uint64
	declaredBytes := uint32(8)
	lengthPresent, _, lengthError := httpQueryHeaders.Call(request, 5|0x08000000, 0, uintptr(unsafe.Pointer(&declared)), uintptr(unsafe.Pointer(&declaredBytes)), 0)
	if lengthPresent == 0 && lengthError != syscall.Errno(12150) {
		return nil, "", fmt.Errorf("WinHttpQueryHeaders Content-Length: %w", lengthError)
	}
	if lengthPresent != 0 && declared > uint64(maxBytes) {
		return nil, "", errors.New("ExtUI response exceeds limit")
	}
	var header [512]uint16
	headerBytes := uint32(len(header) * 2)
	if ok, _, err := httpQueryHeaders.Call(request, 1, 0, uintptr(unsafe.Pointer(&header[0])), uintptr(unsafe.Pointer(&headerBytes)), 0); ok == 0 && err != syscall.Errno(12150) {
		return nil, "", fmt.Errorf("WinHttpQueryHeaders Content-Type: %w", err)
	}
	contentType := syscall.UTF16ToString(header[:])
	var body []byte
	var buffer [16 * 1024]byte
	pin.Pin(&buffer[0])
	for {
		if err := ctx.Err(); err != nil {
			return nil, "", err
		}
		length := min(int64(len(buffer)), maxBytes+1-int64(len(body)))
		if ok, _, err := httpReadData.Call(request, uintptr(unsafe.Pointer(&buffer[0])), uintptr(length), 0); ok == 0 {
			return nil, "", fmt.Errorf("WinHttpReadData: %w", err)
		}
		count, err := state.wait(ctx, httpReadComplete)
		if err != nil {
			return nil, "", err
		}
		if count == 0 {
			if lengthPresent != 0 && uint64(len(body)) != declared {
				return nil, "", errors.New("ExtUI response was truncated")
			}
			return body, contentType, ctx.Err()
		}
		body = append(body, buffer[:count]...)
		if int64(len(body)) > maxBytes {
			return nil, "", errors.New("ExtUI response exceeds limit")
		}
	}
}
