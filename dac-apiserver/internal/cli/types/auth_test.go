package types

import (
	"testing"

	"github.com/bytedance/sonic"
)

func TestLoginDataIgnoresResponseBodyToken(t *testing.T) {
	var data LoginData
	if err := sonic.Unmarshal([]byte(`{"token":"legacy-body-token","expire":"2026-08-05T12:00:00Z"}`), &data); err != nil {
		t.Fatalf("unmarshal login data: %v", err)
	}

	if data.Token != "" {
		t.Fatalf("expected response body token to be ignored, got %q", data.Token)
	}
}
