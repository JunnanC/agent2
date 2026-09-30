package main

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

const (
	defaultListenAddress = "0.0.0.0:8080"
	defaultTargetURL     = "http://127.0.0.1:3000"
	defaultTokenFile     = "/run/secrets/workspace_upstream_token"
	upstreamTokenHeader  = "X-Workspace-Upstream-Token"
	webIDEPathPrefix     = "/webide"
)

type router struct {
	proxy        *httputil.ReverseProxy
	target       *url.URL
	healthClient *http.Client
	tokenDigest  [sha256.Size]byte
}

func envOrDefault(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func loadTokenDigest(path string) ([sha256.Size]byte, error) {
	var empty [sha256.Size]byte
	content, err := os.ReadFile(path)
	if err != nil {
		return empty, fmt.Errorf("read upstream token file: %w", err)
	}
	token := strings.TrimSpace(string(content))
	if len(token) < 32 || len(token) > 4096 {
		return empty, errors.New("upstream token must contain between 32 and 4096 bytes")
	}
	return sha256.Sum256([]byte(token)), nil
}

func newRouter(target *url.URL, tokenDigest [sha256.Size]byte) *router {
	proxy := httputil.NewSingleHostReverseProxy(target)
	director := proxy.Director
	proxy.Director = func(request *http.Request) {
		incomingHost := request.Host
		director(request)
		request.URL.Path = strings.TrimPrefix(request.URL.Path, webIDEPathPrefix)
		if request.URL.Path == "" {
			request.URL.Path = "/"
		}
		request.Host = target.Host
		request.Header.Set("X-Forwarded-Host", incomingHost)
		request.Header.Set("X-Forwarded-Prefix", webIDEPathPrefix)
		request.Header.Del(upstreamTokenHeader)
	}
	proxy.ModifyResponse = func(response *http.Response) error {
		location, err := url.Parse(response.Header.Get("Location"))
		if err != nil || location.String() == "" {
			return nil
		}
		if location.IsAbs() && location.Scheme == target.Scheme && location.Host == target.Host {
			location.Scheme = ""
			location.Host = ""
		}
		if !location.IsAbs() && strings.HasPrefix(location.Path, "/") && !strings.HasPrefix(location.Path, webIDEPathPrefix+"/") {
			location.Path = webIDEPathPrefix + location.Path
			location.RawPath = ""
		}
		response.Header.Set("Location", location.String())
		return nil
	}
	proxy.ErrorHandler = func(response http.ResponseWriter, _ *http.Request, err error) {
		log.Printf("workspace upstream unavailable: %v", err)
		http.Error(response, "workspace unavailable", http.StatusBadGateway)
	}
	return &router{
		proxy:        proxy,
		target:       target,
		healthClient: &http.Client{Timeout: 2 * time.Second},
		tokenDigest:  tokenDigest,
	}
}

func (handler *router) authorized(request *http.Request) bool {
	presented := sha256.Sum256([]byte(request.Header.Get(upstreamTokenHeader)))
	return subtle.ConstantTimeCompare(presented[:], handler.tokenDigest[:]) == 1
}

func (handler *router) health(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet && request.Method != http.MethodHead {
		response.Header().Set("Allow", "GET, HEAD")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	probeURL := *handler.target
	probeURL.Path = "/healthz"
	probeRequest, err := http.NewRequestWithContext(request.Context(), http.MethodGet, probeURL.String(), nil)
	if err != nil {
		http.Error(response, "not ready", http.StatusServiceUnavailable)
		return
	}
	probeResponse, err := handler.healthClient.Do(probeRequest)
	if err != nil {
		http.Error(response, "not ready", http.StatusServiceUnavailable)
		return
	}
	defer probeResponse.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(probeResponse.Body, 4096))
	if probeResponse.StatusCode != http.StatusOK {
		http.Error(response, "not ready", http.StatusServiceUnavailable)
		return
	}
	response.Header().Set("Cache-Control", "no-store")
	response.Header().Set("Content-Type", "text/plain; charset=utf-8")
	response.Header().Set("X-Content-Type-Options", "nosniff")
	response.WriteHeader(http.StatusOK)
	if request.Method != http.MethodHead {
		_, _ = io.WriteString(response, "ok")
	}
}

func (handler *router) ServeHTTP(response http.ResponseWriter, request *http.Request) {
	if request.URL.Path == "/healthz" {
		handler.health(response, request)
		return
	}
	if request.URL.Path != webIDEPathPrefix && !strings.HasPrefix(request.URL.Path, webIDEPathPrefix+"/") {
		http.NotFound(response, request)
		return
	}
	if !handler.authorized(request) {
		http.Error(response, "forbidden", http.StatusForbidden)
		return
	}
	if request.URL.Path == webIDEPathPrefix {
		http.Redirect(response, request, webIDEPathPrefix+"/", http.StatusPermanentRedirect)
		return
	}
	handler.proxy.ServeHTTP(response, request)
}

func probe() error {
	client := &http.Client{Timeout: 2 * time.Second}
	response, err := client.Get("http://127.0.0.1:8080/healthz")
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("health endpoint returned %d", response.StatusCode)
	}
	return nil
}

func run() error {
	target, err := url.Parse(envOrDefault("WORKSPACE_CODE_SERVER_URL", defaultTargetURL))
	if err != nil || target.Scheme != "http" || target.Host == "" || target.User != nil || target.Path != "" || target.RawQuery != "" || target.Fragment != "" {
		return errors.New("WORKSPACE_CODE_SERVER_URL must be an http URL without credentials")
	}
	tokenDigest, err := loadTokenDigest(envOrDefault("WORKSPACE_UPSTREAM_TOKEN_FILE", defaultTokenFile))
	if err != nil {
		return err
	}

	server := &http.Server{
		Addr:              envOrDefault("WORKSPACE_ROUTER_ADDR", defaultListenAddress),
		Handler:           newRouter(target, tokenDigest),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       2 * time.Minute,
		MaxHeaderBytes:    32 * 1024,
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
	}()
	log.Printf("workspace router listening on %s", server.Addr)
	err = server.ListenAndServe()
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func main() {
	if len(os.Args) == 2 && os.Args[1] == "healthcheck" {
		if err := probe(); err != nil {
			os.Exit(1)
		}
		return
	}
	if err := run(); err != nil {
		log.Printf("workspace router stopped: %v", err)
		os.Exit(1)
	}
}
