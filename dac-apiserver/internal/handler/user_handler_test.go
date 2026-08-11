package handler

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"strings"
	"testing"
	"time"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/config"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

func newAuthTestHandler(t *testing.T) *UserHandler {
	t.Helper()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	return NewUserHandler(nil, config.JWTConfig{
		Secret:     "test-secret-that-is-long-enough",
		Timeout:    15 * time.Minute,
		MaxRefresh: 7 * 24 * time.Hour,
	}, logger)
}

func TestRefreshResponseDoesNotExposeBearerToken(t *testing.T) {
	h := newAuthTestHandler(t)
	var c app.RequestContext

	h.authMiddleware.RefreshResponse(
		context.Background(),
		&c,
		200,
		"sensitive-bearer-token",
		time.Unix(1_800_000_000, 0),
	)

	var body struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(c.Response.Body(), &body); err != nil {
		t.Fatalf("decode refresh response: %v", err)
	}
	if _, exists := body.Data["token"]; exists {
		t.Fatal("refresh response must not expose the bearer token when it is set as an HttpOnly cookie")
	}
}

func TestLoginResponseDoesNotExposeBearerToken(t *testing.T) {
	h := newAuthTestHandler(t)
	var c app.RequestContext
	c.Set("user", &entity.User{
		ID:        "user-1",
		Username:  "alice",
		Role:      "admin",
		CreatedAt: time.Unix(1_700_000_000, 0),
	})

	h.authMiddleware.LoginResponse(
		context.Background(),
		&c,
		200,
		"sensitive-bearer-token",
		time.Unix(1_800_000_000, 0),
	)

	var body struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(c.Response.Body(), &body); err != nil {
		t.Fatalf("decode login response: %v", err)
	}
	if _, exists := body.Data["token"]; exists {
		t.Fatal("browser login response must keep the bearer token in the HttpOnly Set-Cookie header only")
	}
}

func TestTokenLookupDoesNotAcceptQueryStringCredentials(t *testing.T) {
	h := newAuthTestHandler(t)

	if strings.Contains(h.authMiddleware.TokenLookup, "query:") {
		t.Fatalf("query-string JWT lookup leaks credentials: %q", h.authMiddleware.TokenLookup)
	}
	if !strings.Contains(h.authMiddleware.TokenLookup, "header: Authorization") ||
		!strings.Contains(h.authMiddleware.TokenLookup, "cookie: dac_token") {
		t.Fatalf("expected header and cookie token lookup, got %q", h.authMiddleware.TokenLookup)
	}
}
