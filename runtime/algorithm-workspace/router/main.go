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
	defaultListenAddress   = "0.0.0.0:8080"
	defaultWebIDEURL       = "http://127.0.0.1:3000"
	defaultTerminalURL     = "http://127.0.0.1:7681"
	defaultSaveBridgeURL   = "http://127.0.0.1:3001"
	defaultTokenFile       = "/run/secrets/workspace_upstream_token"
	upstreamTokenHeader    = "X-Workspace-Upstream-Token"
	webIDEPathPrefix       = "/webide"
	saveBridgePathPrefix   = "/webide/edu-control"
	terminalPathPrefix     = "/terminal"
	responseBodyProbeLimit = 4096
)

type router struct {
	healthClient *http.Client
	tokenDigest  [sha256.Size]byte
	capabilities []*capabilityProxy
}

type capabilityProxy struct {
	proxy       *httputil.ReverseProxy
	target      *url.URL
	pathPrefix  string
	stripPrefix bool
	healthProbe bool
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

/* newCapabilityProxy dispatches one /<prefix>/ capability route to an upstream tool.
   The workspace gateway keeps the capability prefix (<prefix>/<tail>) in the upstream
   path; webide strips it because code-server derives its base URL from
   X-Forwarded-Prefix, terminal keeps it because ttyd is started with --base-path. */
func newCapabilityProxy(target *url.URL, pathPrefix string, stripPrefix, healthProbe bool) *capabilityProxy {
	proxy := httputil.NewSingleHostReverseProxy(target)
	director := proxy.Director
	proxy.Director = func(request *http.Request) {
		incomingHost := request.Host
		director(request)
		if stripPrefix {
			request.URL.Path = strings.TrimPrefix(request.URL.Path, pathPrefix)
			if request.URL.Path == "" {
				request.URL.Path = "/"
			}
			request.Header.Set("X-Forwarded-Prefix", pathPrefix)
		}
		request.Host = target.Host
		request.Header.Set("X-Forwarded-Host", incomingHost)
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
		if !location.IsAbs() && strings.HasPrefix(location.Path, "/") && !strings.HasPrefix(location.Path, pathPrefix+"/") {
			location.Path = pathPrefix + location.Path
			location.RawPath = ""
		}
		response.Header.Set("Location", location.String())
		return nil
	}
	proxy.ErrorHandler = func(response http.ResponseWriter, _ *http.Request, err error) {
		log.Printf("workspace upstream unavailable (%s): %v", pathPrefix, err)
		http.Error(response, "workspace unavailable", http.StatusBadGateway)
	}
	return &capabilityProxy{
		proxy:       proxy,
		target:      target,
		pathPrefix:  pathPrefix,
		stripPrefix: stripPrefix,
		healthProbe: healthProbe,
	}
}

func (handler *router) authorized(request *http.Request) bool {
	presented := sha256.Sum256([]byte(request.Header.Get(upstreamTokenHeader)))
	return subtle.ConstantTimeCompare(presented[:], handler.tokenDigest[:]) == 1
}

func newRouter(webIDE, terminal, saveBridge *url.URL, tokenDigest [sha256.Size]byte) *router {
	return &router{
		healthClient: &http.Client{Timeout: 2 * time.Second},
		tokenDigest:  tokenDigest,
		capabilities: []*capabilityProxy{
			newCapabilityProxy(saveBridge, saveBridgePathPrefix, true, false),
			newCapabilityProxy(webIDE, webIDEPathPrefix, true, true),
			newCapabilityProxy(terminal, terminalPathPrefix, false, false),
		},
	}
}

func (handler *router) ready(target *url.URL) error {
	probeRequest, err := http.NewRequestWithContext(context.Background(), http.MethodGet, target.String()+"/healthz", nil)
	if err != nil {
		return err
	}
	probeResponse, err := handler.healthClient.Do(probeRequest)
	if err != nil {
		return err
	}
	defer probeResponse.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(probeResponse.Body, responseBodyProbeLimit))
	if probeResponse.StatusCode != http.StatusOK {
		return fmt.Errorf("health endpoint returned %d", probeResponse.StatusCode)
	}
	return nil
}

func (handler *router) health(response http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet && request.Method != http.MethodHead {
		response.Header().Set("Allow", "GET, HEAD")
		http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	for _, capability := range handler.capabilities {
		if !capability.healthProbe {
			continue
		}
		if err := handler.ready(capability.target); err != nil {
			log.Printf("workspace readiness check failed (%s): %v", capability.pathPrefix, err)
			http.Error(response, "not ready", http.StatusServiceUnavailable)
			return
		}
	}
	response.Header().Set("Cache-Control", "no-store")
	response.Header().Set("Content-Type", "text/plain; charset=utf-8")
	response.Header().Set("X-Content-Type-Options", "nosniff")
	response.WriteHeader(http.StatusOK)
	if request.Method != http.MethodHead {
		_, _ = io.WriteString(response, "ok")
	}
}

func (handler *router) capability(path string) *capabilityProxy {
	for _, candidate := range handler.capabilities {
		if path == candidate.pathPrefix || strings.HasPrefix(path, candidate.pathPrefix+"/") {
			return candidate
		}
	}
	return nil
}

func (handler *router) ServeHTTP(response http.ResponseWriter, request *http.Request) {
	if request.URL.Path == "/healthz" {
		handler.health(response, request)
		return
	}
	capability := handler.capability(request.URL.Path)
	if capability == nil {
		http.NotFound(response, request)
		return
	}
	if !handler.authorized(request) {
		http.Error(response, "forbidden", http.StatusForbidden)
		return
	}
	if request.URL.Path == capability.pathPrefix {
		http.Redirect(response, request, capability.pathPrefix+"/", http.StatusPermanentRedirect)
		return
	}
	capability.proxy.ServeHTTP(response, request)
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

func parseTarget(name, fallback string) (*url.URL, error) {
	target, err := url.Parse(envOrDefault(name, fallback))
	if err != nil || target.Scheme != "http" || target.Host == "" || target.User != nil || target.Path != "" || target.RawQuery != "" || target.Fragment != "" {
		return nil, errors.New(name + " must be an http URL without credentials")
	}
	return target, nil
}

func run() error {
	codeServer, err := parseTarget("WORKSPACE_CODE_SERVER_URL", defaultWebIDEURL)
	if err != nil {
		return err
	}
	terminal, err := parseTarget("WORKSPACE_TERMINAL_URL", defaultTerminalURL)
	if err != nil {
		return err
	}
	saveBridge, err := parseTarget("WORKSPACE_SAVE_BRIDGE_URL", defaultSaveBridgeURL)
	if err != nil {
		return err
	}
	tokenDigest, err := loadTokenDigest(envOrDefault("WORKSPACE_UPSTREAM_TOKEN_FILE", defaultTokenFile))
	if err != nil {
		return err
	}

	server := &http.Server{
		Addr:    envOrDefault("WORKSPACE_ROUTER_ADDR", defaultListenAddress),
		Handler: newRouter(codeServer, terminal, saveBridge, tokenDigest),
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
