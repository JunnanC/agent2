package main

import (
	"bufio"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

const testToken = "workspace-test-token-with-at-least-thirty-two-bytes"

func targetURL(t *testing.T, value string) *url.URL {
	t.Helper()
	parsed, err := url.Parse(value)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}

func request(t *testing.T, client *http.Client, method, endpoint, token string) (*http.Response, []byte) {
	t.Helper()
	req, err := http.NewRequest(method, endpoint, nil)
	if err != nil {
		t.Fatal(err)
	}
	if token != "" {
		req.Header.Set(upstreamTokenHeader, token)
	}
	response, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, 65536))
	if err != nil {
		t.Fatal(err)
	}
	err = response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	return response, body
}

func noRedirectClient(server *httptest.Server) *http.Client {
	client := server.Client()
	client.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return client
}

func testRouterPair(t *testing.T) (webIDEURL, terminalURL string, close func()) {
	t.Helper()
	webIDE := httptest.NewServer(http.NotFoundHandler())
	terminal := httptest.NewServer(http.NotFoundHandler())
	return webIDE.URL, terminal.URL, func() {
		webIDE.Close()
		terminal.Close()
	}
}

func TestWebIDERoutesRequireTokenStripPrefixAndRewriteRedirects(t *testing.T) {
	var backend *httptest.Server
	backend = httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get(upstreamTokenHeader) != "" {
			t.Error("upstream token reached code-server")
		}
		if request.URL.Path == "/redirect" {
			response.Header().Set("Location", backend.URL+"/editor?folder=%2Fworkspace")
			response.WriteHeader(http.StatusTemporaryRedirect)
			return
		}
		if request.URL.Path != "/static/app.js" && request.URL.Path != "/editor" {
			t.Errorf("unexpected upstream path: %s", request.URL.Path)
		}
		response.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()
	_, terminalURL, closeBackends := testRouterPair(t)
	defer closeBackends()
	server := httptest.NewServer(newRouter(targetURL(t, backend.URL), targetURL(t, terminalURL), sha256.Sum256([]byte(testToken))))
	defer server.Close()

	for _, token := range []string{"", "wrong-token"} {
		response, _ := request(t, server.Client(), http.MethodGet, server.URL+"/webide/static/app.js", token)
		if response.StatusCode != http.StatusForbidden {
			t.Fatalf("token %q returned %d", token, response.StatusCode)
		}
	}
	response, _ := request(t, server.Client(), http.MethodGet, server.URL+"/webide/static/app.js", testToken)
	if response.StatusCode != http.StatusOK {
		t.Fatalf("authorized request returned %d", response.StatusCode)
	}
	response, _ = request(t, noRedirectClient(server), http.MethodGet, server.URL+"/webide/redirect", testToken)
	if response.StatusCode != http.StatusTemporaryRedirect || response.Header.Get("Location") != "/webide/editor?folder=%2Fworkspace" {
		t.Fatalf("internal redirect was not rewritten: %d %q", response.StatusCode, response.Header.Get("Location"))
	}
}

func TestTerminalRoutesRequireTokenAndKeepPrefixUpstream(t *testing.T) {
	var backend *httptest.Server
	backend = httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get(upstreamTokenHeader) != "" {
			t.Error("upstream token reached ttyd")
		}
		if request.URL.Path != "/terminal/" && request.URL.Path != "/terminal/ws" {
			t.Errorf("unexpected upstream path: %s", request.URL.Path)
		}
		connection, buffer, err := response.(http.Hijacker).Hijack()
		if err != nil {
			t.Error(err)
			return
		}
		defer connection.Close()
		acceptSource := request.Header.Get("Sec-WebSocket-Key") + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
		acceptDigest := sha1.Sum([]byte(acceptSource))
		_, _ = fmt.Fprintf(buffer, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n", base64.StdEncoding.EncodeToString(acceptDigest[:]))
		_ = buffer.Flush()
	}))
	defer backend.Close()

	pageServer := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get(upstreamTokenHeader) != "" {
			t.Error("upstream token reached ttyd page backend")
		}
		if request.URL.Path != "/terminal/" {
			t.Errorf("unexpected upstream path: %s", request.URL.Path)
		}
		response.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = fmt.Fprint(response, "<!DOCTYPE html><title>ttyd - Terminal</title>")
	}))
	defer pageServer.Close()

	webIDEURL, _, closeBackends := testRouterPair(t)
	defer closeBackends()
	router := newRouter(
		targetURL(t, webIDEURL),
		targetURL(t, pageServer.URL),
		sha256.Sum256([]byte(testToken)),
	)
	server := httptest.NewServer(router)
	defer server.Close()

	for _, token := range []string{"", "wrong-token"} {
		response, _ := request(t, server.Client(), http.MethodGet, server.URL+"/terminal/", token)
		if response.StatusCode != http.StatusForbidden {
			t.Fatalf("token %q returned %d", token, response.StatusCode)
		}
	}

	response, body := request(t, server.Client(), http.MethodGet, server.URL+"/terminal/", testToken)
	if response.StatusCode != http.StatusOK {
		t.Fatalf("authorized terminal request returned %d", response.StatusCode)
	}
	if !strings.Contains(string(body), "ttyd - Terminal") {
		t.Fatalf("terminal page marker missing")
	}

	response, _ = request(t, noRedirectClient(server), http.MethodGet, server.URL+"/terminal", testToken)
	if response.StatusCode != http.StatusPermanentRedirect || response.Header.Get("Location") != "/terminal/" {
		t.Fatalf("terminal redirect not generated: %d %q", response.StatusCode, response.Header.Get("Location"))
	}
}

func TestTerminalWebSocketUpgradeKeepsPrefix(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get(upstreamTokenHeader) != "" {
			t.Error("upstream token reached websocket backend")
		}
		if request.URL.Path != "/terminal/ws" {
			t.Errorf("expected terminal prefix in upstream websocket path, got %s", request.URL.Path)
		}
		connection, buffer, err := response.(http.Hijacker).Hijack()
		if err != nil {
			t.Error(err)
			return
		}
		defer connection.Close()
		acceptSource := request.Header.Get("Sec-WebSocket-Key") + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
		acceptDigest := sha1.Sum([]byte(acceptSource))
		_, _ = fmt.Fprintf(buffer, "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n", base64.StdEncoding.EncodeToString(acceptDigest[:]))
		_ = buffer.Flush()
	}))
	defer backend.Close()

	webIDEURL, _, closeBackends := testRouterPair(t)
	defer closeBackends()
	server := httptest.NewServer(newRouter(targetURL(t, webIDEURL), targetURL(t, backend.URL), sha256.Sum256([]byte(testToken))))
	defer server.Close()

	address := strings.TrimPrefix(server.URL, "http://")
	connection, err := net.DialTimeout("tcp", address, 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = connection.Close() }()
	_, _ = fmt.Fprintf(connection, "GET /terminal/ws HTTP/1.1\r\nHost: %s\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n%s: %s\r\n\r\n", address, upstreamTokenHeader, testToken)
	response, err := http.ReadResponse(bufio.NewReader(connection), &http.Request{Method: http.MethodGet})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusSwitchingProtocols {
		t.Fatalf("websocket upgrade returned %d", response.StatusCode)
	}
}

func TestUnsupportedCapabilityIs404(t *testing.T) {
	webIDEURL, terminalURL, closeBackends := testRouterPair(t)
	defer closeBackends()
	server := httptest.NewServer(newRouter(targetURL(t, webIDEURL), targetURL(t, terminalURL), sha256.Sum256([]byte(testToken))))
	defer server.Close()
	for _, path := range []string{"/notebook/", "/preview/", "/"} {
		response, _ := request(t, server.Client(), http.MethodGet, server.URL+path, testToken)
		if response.StatusCode != http.StatusNotFound {
			t.Fatalf("unsupported capability %s returned %d", path, response.StatusCode)
		}
	}
}

func TestHealthReflectsWorkspaceToolsReadiness(t *testing.T) {
	healthy := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/healthz" {
			t.Fatalf("unexpected health path: %s", request.URL.Path)
		}
		response.WriteHeader(http.StatusOK)
	}))
	defer healthy.Close()
	unavailable := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		http.Error(response, "down", http.StatusServiceUnavailable)
	}))
	defer unavailable.Close()

	// Terminal 的 /healthz 是 404(真实 ttyd 没有该端点):health 必须 200,
	// 证明 health 探测只覆盖声明了 healthProbe 的 capability(webide)。
	_, terminalURL, closeBackends := testRouterPair(t)
	defer closeBackends()
	server := httptest.NewServer(newRouter(targetURL(t, healthy.URL), targetURL(t, terminalURL), sha256.Sum256([]byte(testToken))))
	defer server.Close()
	response, body := request(t, server.Client(), http.MethodGet, server.URL+"/healthz", "")
	if response.StatusCode != http.StatusOK {
		t.Fatalf("health returned %d", response.StatusCode)
	}
	if string(body) != "ok" {
		t.Fatalf("unexpected health body %q", string(body))
	}

	server2 := httptest.NewServer(newRouter(targetURL(t, unavailable.URL), targetURL(t, terminalURL), sha256.Sum256([]byte(testToken))))
	defer server2.Close()
	response2, _ := request(t, server2.Client(), http.MethodGet, server2.URL+"/healthz", "")
	if response2.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("health of unavailable workspace returned %d", response2.StatusCode)
	}
}
