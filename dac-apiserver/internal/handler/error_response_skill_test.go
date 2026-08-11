package handler

import (
	"encoding/json"
	"errors"
	"fmt"
	"testing"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/protocol"
	"github.com/lvyanru/dac-apiserver/internal/domain"
)

func TestErrorResponse_WrappedInvalidInputUsesDomainMessage(t *testing.T) {
	c := app.NewContext(0)
	c.Request = *protocol.NewRequest("GET", "/", nil)

	inner := domain.NewInvalidInputError("duplicate skillPolicy skill name \"weather\"")
	wrapped := fmt.Errorf("invalid request: %w", inner)
	ErrorResponse(c, wrapped)

	if c.Response.StatusCode() != 400 {
		t.Fatalf("status=%d want 400", c.Response.StatusCode())
	}
	var resp Response
	if err := json.Unmarshal(c.Response.Body(), &resp); err != nil {
		t.Fatalf("unmarshal: %v body=%s", err, c.Response.Body())
	}
	if resp.Code != "INVALID_INPUT" {
		t.Fatalf("code=%s", resp.Code)
	}
	if resp.Message != "duplicate skillPolicy skill name \"weather\"" {
		t.Fatalf("message=%q", resp.Message)
	}
}

func TestErrorResponse_PlainInvalidInputFallback(t *testing.T) {
	c := app.NewContext(0)
	c.Request = *protocol.NewRequest("GET", "/", nil)

	ErrorResponse(c, fmt.Errorf("%w: skillPolicy empty", domain.ErrInvalidInput))
	if c.Response.StatusCode() != 400 {
		t.Fatalf("status=%d", c.Response.StatusCode())
	}
	var resp Response
	_ = json.Unmarshal(c.Response.Body(), &resp)
	if resp.Message == "an error occurred" {
		t.Fatalf("expected concrete message, got %q", resp.Message)
	}
	if !errors.Is(fmt.Errorf("%w: x", domain.ErrInvalidInput), domain.ErrInvalidInput) {
		t.Fatal("sanity")
	}
}
