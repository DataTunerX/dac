package usecase

import (
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

func TestBuildSemanticGroupVectorText(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name        string
		groupName   string
		description string
		members     []domain.SemanticGroupMemberDetail
		want        string
	}{
		{
			name:      "name only",
			groupName: "sales",
			want:      "语义组名称: sales",
		},
		{
			name:        "with description",
			groupName:   "sales",
			description: "Sales data group",
			want:        "语义组名称: sales\n描述: Sales data group",
		},
		{
			name:      "sorted member ids",
			groupName: "sales",
			members: []domain.SemanticGroupMemberDetail{
				{Relation: domain.DDGroupRelation{SemanticDomainID: "sd-2"}},
				{Relation: domain.DDGroupRelation{SemanticDomainID: "sd-1"}},
				{Relation: domain.DDGroupRelation{SemanticDomainID: "sd-2"}},
			},
			want: "语义组名称: sales\n成员语义域ID: sd-1, sd-2",
		},
		{
			name:        "skip blank description",
			groupName:   "sales",
			description: "   ",
			want:        "语义组名称: sales",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			got := buildSemanticGroupVectorText(tt.groupName, tt.description, tt.members)
			if got != tt.want {
				t.Fatalf("buildSemanticGroupVectorText() = %q, want %q", got, tt.want)
			}
		})
	}
}
