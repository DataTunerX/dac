package dto

import (
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

func TestToSkillInfoResponse(t *testing.T) {
	got := ToSkillInfoResponse(domain.SkillInfo{
		Name:              "hashgen",
		Namespace:         "default",
		Description:       "desc",
		Version:           "2.0.0",
		Filename:          "hashgen-2.0.0.zip",
		AvailableVersions: []string{"2.0.0", "1.0.0"},
	})
	if got.Name != "hashgen" || got.Namespace != "default" || got.Version != "2.0.0" {
		t.Fatalf("unexpected response: %#v", got)
	}
	if len(got.AvailableVersions) != 2 || got.AvailableVersions[0] != "2.0.0" {
		t.Fatalf("versions=%v", got.AvailableVersions)
	}
}

func TestToSkillInfoResponse_NilVersions(t *testing.T) {
	got := ToSkillInfoResponse(domain.SkillInfo{Name: "x"})
	if got.AvailableVersions == nil || len(got.AvailableVersions) != 0 {
		t.Fatalf("want empty slice, got %#v", got.AvailableVersions)
	}
}

func TestToSkillNamespaceResponse(t *testing.T) {
	got := ToSkillNamespaceResponse(domain.SkillNamespace{ID: "team-a", Visibility: "public"})
	if got.ID != "team-a" || got.Visibility != "public" {
		t.Fatalf("unexpected: %#v", got)
	}
}
