package client

import (
	"testing"

	"github.com/cloudwego/hertz/pkg/protocol"
)

func TestResponseCookieValueReturnsNamedCookie(t *testing.T) {
	var header protocol.ResponseHeader
	var cookie protocol.Cookie
	cookie.SetKey("dac_token")
	cookie.SetValue("cli-bearer-token")
	header.SetCookie(&cookie)

	value, ok := responseCookieValue(&header, "dac_token")
	if !ok {
		t.Fatal("expected dac_token response cookie")
	}
	if value != "cli-bearer-token" {
		t.Fatalf("unexpected cookie value %q", value)
	}
}
