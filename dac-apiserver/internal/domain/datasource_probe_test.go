package domain

import (
	"errors"
	"testing"
)

func TestProbeDataSourceRequest_Validate(t *testing.T) {
	tests := []struct {
		name    string
		req     *ProbeDataSourceRequest
		wantErr bool
	}{
		{"nil request", nil, true},
		{"empty type", &ProbeDataSourceRequest{Type: "", Host: "h", Port: 1}, true},
		{"whitespace type", &ProbeDataSourceRequest{Type: "  ", Host: "h", Port: 1}, true},
		{"empty host", &ProbeDataSourceRequest{Type: "mysql", Host: "", Port: 1}, true},
		{"port too low", &ProbeDataSourceRequest{Type: "mysql", Host: "h", Port: 0}, true},
		{"port too high", &ProbeDataSourceRequest{Type: "mysql", Host: "h", Port: 70000}, true},
		{"valid minimal", &ProbeDataSourceRequest{Type: "mysql", Host: "h", Port: 3306}, false},
		{"valid with creds", &ProbeDataSourceRequest{Type: "postgres", Host: "h", Port: 5432, User: "u", Password: "p"}, false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.req.Validate()
			if (err != nil) != tc.wantErr {
				t.Fatalf("err=%v wantErr=%v", err, tc.wantErr)
			}
			if tc.wantErr && !errors.Is(err, ErrInvalidInput) {
				t.Fatalf("err=%v want errors.Is(_, ErrInvalidInput)", err)
			}
		})
	}
}
