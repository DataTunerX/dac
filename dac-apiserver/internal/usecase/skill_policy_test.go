package usecase

import (
	"errors"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

func TestValidateSkillPolicy_OK(t *testing.T) {
	err := validateSkillPolicy(
		entity.SkillPolicy{Skills: []entity.SkillRef{
			{Namespace: "default", Name: "weather", Version: "1.0.0"},
			{Namespace: "team-a", Name: "report"},
		}},
		entity.AgentCard{Skills: []entity.AgentSkill{
			{ID: "weather", Name: "weather", Description: "d1"},
			{ID: "report", Name: "report", Description: "d2"},
		}},
	)
	if err != nil {
		t.Fatalf("unexpected: %v", err)
	}
}

func TestValidateSkillPolicy_DuplicateName(t *testing.T) {
	err := validateSkillPolicy(
		entity.SkillPolicy{Skills: []entity.SkillRef{
			{Namespace: "default", Name: "weather"},
			{Namespace: "team-a", Name: "weather"},
		}},
		entity.AgentCard{Skills: []entity.AgentSkill{
			{ID: "weather", Name: "weather", Description: "d"},
		}},
	)
	if err == nil {
		t.Fatal("expected duplicate name error")
	}
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want InvalidInput, got %v", err)
	}
}

func TestValidateSkillPolicy_Empty(t *testing.T) {
	err := validateSkillPolicy(entity.SkillPolicy{}, entity.AgentCard{})
	if err == nil {
		t.Fatal("expected empty skills error")
	}
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want InvalidInput, got %v", err)
	}
}

func TestValidateSkillPolicy_EmptyCard(t *testing.T) {
	err := validateSkillPolicy(
		entity.SkillPolicy{Skills: []entity.SkillRef{
			{Namespace: "default", Name: "weather"},
		}},
		entity.AgentCard{},
	)
	if err == nil {
		t.Fatal("expected empty agentCard.skills error")
	}
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want InvalidInput, got %v", err)
	}
}

func TestValidateSkillPolicy_CardMismatch(t *testing.T) {
	err := validateSkillPolicy(
		entity.SkillPolicy{Skills: []entity.SkillRef{
			{Namespace: "default", Name: "weather"},
		}},
		entity.AgentCard{Skills: []entity.AgentSkill{
			{ID: "other", Name: "other", Description: "x"},
		}},
	)
	if err == nil {
		t.Fatal("expected card/policy mismatch error")
	}
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want InvalidInput, got %v", err)
	}
	var de *domain.DomainError
	if !errors.As(err, &de) {
		t.Fatalf("want DomainError, got %T %v", err, err)
	}
	if de.UserMessage() == "" {
		t.Fatal("empty user message")
	}
}

func TestValidateSkillPolicy_MissingNamespace(t *testing.T) {
	err := validateSkillPolicy(
		entity.SkillPolicy{Skills: []entity.SkillRef{
			{Namespace: "", Name: "weather"},
		}},
		entity.AgentCard{Skills: []entity.AgentSkill{
			{ID: "weather", Name: "weather", Description: "d"},
		}},
	)
	if err == nil {
		t.Fatal("expected missing namespace error")
	}
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want InvalidInput, got %v", err)
	}
}

func TestValidateOptionalSkillPolicyRefs_EmptyOK(t *testing.T) {
	if err := validateOptionalSkillPolicyRefs(entity.SkillPolicy{}); err != nil {
		t.Fatalf("empty policy should be ok for normal: %v", err)
	}
}

func TestValidateOptionalSkillPolicyRefs_OK(t *testing.T) {
	err := validateOptionalSkillPolicyRefs(entity.SkillPolicy{Skills: []entity.SkillRef{
		{Namespace: "default", Name: "weather"},
		{Namespace: "team-a", Name: "web_fetch"},
	}})
	if err != nil {
		t.Fatalf("unexpected: %v", err)
	}
}

func TestValidateOptionalSkillPolicyRefs_Duplicate(t *testing.T) {
	err := validateOptionalSkillPolicyRefs(entity.SkillPolicy{Skills: []entity.SkillRef{
		{Namespace: "default", Name: "weather"},
		{Namespace: "team-a", Name: "weather"},
	}})
	if err == nil {
		t.Fatal("expected duplicate name error")
	}
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want InvalidInput, got %v", err)
	}
}

func TestRejectSkillPolicyForDS(t *testing.T) {
	if err := rejectSkillPolicyForDS(entity.SkillPolicy{}); err != nil {
		t.Fatalf("empty should be ok: %v", err)
	}
	err := rejectSkillPolicyForDS(entity.SkillPolicy{Skills: []entity.SkillRef{
		{Namespace: "default", Name: "weather"},
	}})
	if err == nil {
		t.Fatal("expected reject non-empty skillPolicy for ds")
	}
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want InvalidInput, got %v", err)
	}
}
