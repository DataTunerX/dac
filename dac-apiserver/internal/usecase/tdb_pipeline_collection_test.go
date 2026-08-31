package usecase

import (
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

func TestDefaultCollectionForTarget(t *testing.T) {
	cases := []struct {
		name   string
		target domain.TDBPipelineTarget
		want   string
	}{
		{
			name:   "explicit per-target collection wins",
			target: domain.TDBPipelineTarget{ID: "archeology_papers_test", Domain: "archeology", Collection: "academic_papers"},
			want:   "academic_papers",
		},
		{
			// The bug this rule exists for: a fixed global default would file
			// museum material into the papers collection.
			name:   "falls back to the target domain, not the global default",
			target: domain.TDBPipelineTarget{ID: "wwybsj", Domain: "wwybsj"},
			want:   "wwybsj",
		},
		{
			name:   "domain is used even when it differs from the target id",
			target: domain.TDBPipelineTarget{ID: "archeology", Domain: "archeology"},
			want:   "archeology",
		},
		{
			name:   "global default only when the target names neither",
			target: domain.TDBPipelineTarget{ID: "odd"},
			want:   "fallback",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := DefaultCollectionForTarget(tc.target, "fallback"); got != tc.want {
				t.Fatalf("expected %q, got %q", tc.want, got)
			}
		})
	}
}
