package usecase

import (
	"strings"
	"testing"
)

func TestValidateCrossSGMaxHop(t *testing.T) {
	tests := []struct {
		name    string
		hop     string
		wantErr string
	}{
		{name: "empty allowed", hop: ""},
		{name: "whitespace allowed", hop: "  "},
		{name: "single agent", hop: "1"},
		{name: "multi default", hop: "5"},
		{name: "multi min", hop: "2"},
		{name: "zero", hop: "0", wantErr: "must be >= 1"},
		{name: "negative", hop: "-3", wantErr: "must be >= 1"},
		{name: "not integer", hop: "1.5", wantErr: "must be an integer >= 1"},
		{name: "text", hop: "abc", wantErr: "must be an integer >= 1"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateCrossSGMaxHop(tt.hop)
			if tt.wantErr == "" {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				return
			}
			if err == nil {
				t.Fatalf("expected error containing %q", tt.wantErr)
			}
			if !strings.Contains(err.Error(), tt.wantErr) {
				t.Fatalf("error %q, want substring %q", err.Error(), tt.wantErr)
			}
		})
	}
}
