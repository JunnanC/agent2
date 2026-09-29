package main

import (
	"bufio"
	"crypto/sha1"
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

const testToken = "p16-b-test-token-with-at-least-thirty-two-bytes"

func targetURL(t *testing.T, value string) *url.URL {
	t.Helper()
	parsed, err := url.Parse(value)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}

func request(t *testing.T, client *http.Client, method, endpoint, token string) *http.Response {
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
	return response
}

func TestRoutesRequireTokenAndStripItUpstream(t *testing.T) {
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

	handler := newRouter(targetURL(t, backend.URL), sha256.Sum256([]byte(testToken)))
	server := httptest.NewServer(handler)
	defer server.Close()

	for _, token := range []string{"", "wrong-token"} {
		response := request(t, server.Client(), http.MethodGet, server.URL+"/webide/static/app.js", token)
		response.Body.Close()
		if response.StatusCode != http.StatusForbidden {
			t.Fatalf("token %q returned %d", token, response.StatusCode)
		}
	}
	response := request(t, server.Client(), http.MethodGet, server.URL+"/webide/static/app.js", testToken)
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("authorized request returned %d", response.StatusCode)
	}
	noRedirectClient := server.Client()
	noRedirectClient.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	response = request(t, noRedirectClient, http.MethodGet, server.URL+"/webide/redirect", testToken)
	response.Body.Close()
	if response.StatusCode != http.StatusTemporaryRedirect || response.Header.Get("Location") != "/webide/editor?folder=%2Fworkspace" {
		t.Fatalf("internal redirect was not rewritten: %d %q", response.StatusCode, response.Header.Get("Location"))
	}

	response = request(t, server.Client(), http.MethodGet, server.URL+"/terminal/", "")
	response.Body.Close()
	if response.StatusCode != http.StatusNotFound {
		t.Fatalf("unsupported capability returned %d", response.StatusCode)
	}
}

func TestHealthReflectsCodeServerReadiness(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/healthz" {
			t.Fatalf("unexpected health path: %s", request.URL.Path)
		}
		response.WriteHeader(http.StatusOK)
	}))
	defer backend.Close()
	handler := newRouter(targetURL(t, backend.URL), sha256.Sum256([]byte(testToken)))
	server := httptest.NewServer(handler)
	defer server.Close()

	response := request(t, server.Client(), http.MethodGet, server.URL+"/healthz", "")
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("health returned %d", response.StatusCode)
	}
}

func TestWebSocketUpgradeIsProxied(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Header.Get(upstreamTokenHeader) != "" {
			t.Error("upstream token reached websocket backend")
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
	handler := newRouter(targetURL(t, backend.URL), sha256.Sum256([]byte(testToken)))
	server := httptest.NewServer(handler)
	defer server.Close()

	address := strings.TrimPrefix(server.URL, "http://")
	connection, err := net.DialTimeout("tcp", address, 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	_, _ = fmt.Fprintf(connection, "GET /webide/websocket HTTP/1.1\r\nHost: %s\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n%s: %s\r\n\r\n", address, upstreamTokenHeader, testToken)
	response, err := http.ReadResponse(bufio.NewReader(connection), &http.Request{Method: http.MethodGet})
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusSwitchingProtocols {
		t.Fatalf("websocket upgrade returned %d", response.StatusCode)
	}
}
