package tdbpipeline

import (
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

func TestAgentNameForTargetFollowsExistingConvention(t *testing.T) {
	// Matches the hand-created containers: history-tdb-agent, geo-environment-tdb-agent.
	cases := map[string]string{
		"history":                "history-tdb-agent",
		"geo_environment":        "geo-environment-tdb-agent",
		"archeology_papers_test": "archeology-papers-test-tdb-agent",
	}
	for id, want := range cases {
		got := AgentNameForTarget(domain.TDBPipelineTarget{ID: id, Domain: id})
		if got != want {
			t.Errorf("target %q: expected agent %q, got %q", id, want, got)
		}
	}
}

func TestAgentCardNameIsTitleCased(t *testing.T) {
	got := agentCardName(domain.TDBPipelineTarget{ID: "geo_environment"})
	if got != "Geo-Environment-TDB-Agent" {
		t.Fatalf("unexpected agent card name %q", got)
	}
}

func TestAgentReferencesSkill(t *testing.T) {
	container := &entity.AgentContainer{
		SkillPolicy: entity.SkillPolicy{Skills: []entity.SkillRef{
			{Namespace: "default", Name: "tdb-history-qa", Version: "1.0.0"},
		}},
	}
	if !agentReferencesSkill(container, "default", "tdb-history-qa") {
		t.Error("expected the existing skill to be detected")
	}
	if agentReferencesSkill(container, "default", "tdb-archeology-qa") {
		t.Error("expected an absent skill to be reported missing")
	}
}

func TestAgentDefaultsFallbacks(t *testing.T) {
	d := AgentDefaults{}.withFallbacks()
	if d.Namespace != "default" || d.ExpertAgentMaxSteps != "30" || d.OrchestratorAgentMaxLoops != "2" {
		t.Fatalf("unexpected defaults: %+v", d)
	}
}
