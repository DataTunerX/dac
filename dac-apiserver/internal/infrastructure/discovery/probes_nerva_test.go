package discovery

import (
	"encoding/json"
	"testing"

	"github.com/praetorian-inc/nerva/pkg/plugins"
)

func TestMatchFromNerva_Protocols(t *testing.T) {
	cases := []struct {
		name        string
		proto       string
		wantType    string
		wantProduct string
	}{
		{"mysql", "mysql", "mysql", "mysql"},
		{"postgres", "postgres", "postgres", "postgresql"},
		{"redis", "redis", "redis", "redis"},
		{"ssh", "ssh", "ssh", "ssh"},
		{"http bare", "http", "http", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			m := matchFromNerva(plugins.Service{Protocol: tc.proto, Transport: "tcp"})
			if m == nil {
				t.Fatal("expected match")
			}
			if m.ServiceType != tc.wantType {
				t.Fatalf("serviceType=%q want %q", m.ServiceType, tc.wantType)
			}
			if m.Product != tc.wantProduct {
				t.Fatalf("product=%q want %q", m.Product, tc.wantProduct)
			}
		})
	}
}

func TestMatchFromNerva_HTTPTechnologies(t *testing.T) {
	raw, err := json.Marshal(nervaHTTPMeta{
		StatusCode:   200,
		Technologies: []string{"Nginx", "GitLab"},
		FingerprintMetadata: map[string]map[string]any{
			"gitlab": {"version": "17.0.0"},
		},
		ResponseHeaders: map[string][]string{"Server": {"nginx"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	m := matchFromNerva(plugins.Service{Protocol: "http", Raw: raw})
	if m == nil {
		t.Fatal("expected match")
	}
	if m.Product != "gitlab" {
		t.Fatalf("product=%q want gitlab", m.Product)
	}
	if m.Version != "17.0.0" {
		t.Fatalf("version=%q want 17.0.0", m.Version)
	}
	if m.Metadata["http.server"] != "nginx" {
		t.Fatalf("http.server=%q", m.Metadata["http.server"])
	}
}

func TestIsGenericHTTP(t *testing.T) {
	if !isGenericHTTP(&Match{ServiceType: "http"}) {
		t.Fatal("bare http should be generic")
	}
	if !isGenericHTTP(&Match{ServiceType: "http", Product: "nginx"}) {
		t.Fatal("nginx should be enrichable")
	}
	if isGenericHTTP(&Match{ServiceType: "http", Product: "gitlab"}) {
		t.Fatal("gitlab should be concrete")
	}
	if isGenericHTTP(&Match{ServiceType: "mysql", Product: "mysql"}) {
		t.Fatal("mysql should not be treated as http")
	}
}

func TestParsePortSpec_AllAlias(t *testing.T) {
	ports, err := ParsePortSpec("*")
	if err != nil {
		t.Fatal(err)
	}
	if len(ports) != 65535 {
		t.Fatalf("len=%d want 65535", len(ports))
	}
}

func TestDefaultPorts_IncludesSandbox(t *testing.T) {
	want := map[int]bool{3306: true, 5432: true, 6379: true, 8000: true, 8001: true, 8069: true, 8080: true, 8929: true, 9000: true, 9002: true}
	got := map[int]bool{}
	for _, p := range DefaultPorts() {
		got[p] = true
	}
	for p := range want {
		if !got[p] {
			t.Fatalf("DefaultPorts missing %d", p)
		}
	}
}
