package entity

import "testing"

func TestNormalizePDFLoader(t *testing.T) {
	tests := []struct {
		in   string
		want string
	}{
		{"", ""},
		{"auto", "auto"},
		{"AUTO", "auto"},
		{" ocr ", "ocr"},
		{"text", "text"},
		{"mineru", ""},
		{"unknown", ""},
	}

	for _, tt := range tests {
		if got := NormalizePDFLoader(tt.in); got != tt.want {
			t.Fatalf("NormalizePDFLoader(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
}
