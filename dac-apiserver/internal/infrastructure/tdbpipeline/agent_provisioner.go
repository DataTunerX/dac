package tdbpipeline

import (
	"context"
	"fmt"
	"strings"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// AgentDefaults are the DataAgentContainer settings a generated skill agent is
// created with. They mirror the hand-created *-tdb-agent containers.
type AgentDefaults struct {
	Namespace                 string
	ExpertLLM                 string
	PlannerLLM                string
	ExpertAgentMaxSteps       string
	OrchestratorAgentMaxLoops string
}

func (d AgentDefaults) withFallbacks() AgentDefaults {
	if d.Namespace == "" {
		d.Namespace = "default"
	}
	if d.ExpertAgentMaxSteps == "" {
		d.ExpertAgentMaxSteps = "30"
	}
	if d.OrchestratorAgentMaxLoops == "" {
		d.OrchestratorAgentMaxLoops = "2"
	}
	return d
}

// EnsureAgent makes sure a skill agent exists that loads skillName.
//
// Three cases: no agent -> create one bound to this skill; an agent that
// already lists the skill -> nothing to do; an agent that exists without the
// skill -> append it, so a target whose agent predates the skill still picks
// it up rather than silently ignoring the new corpus.
func (p *SkillProvisioner) EnsureAgent(ctx context.Context, target domain.TDBPipelineTarget, skillName string) (string, error) {
	if !p.enabled || !p.agentsEnabled {
		return "", nil
	}
	if p.agents == nil {
		return "", fmt.Errorf("agent creation enabled without an agent repository")
	}
	if strings.TrimSpace(skillName) == "" {
		return "", fmt.Errorf("cannot create an agent without a skill name")
	}

	defaults := p.agentDefaults.withFallbacks()
	agentName := AgentNameForTarget(target)
	if agentName == "" {
		return "", fmt.Errorf("cannot derive an agent name for target %q", target.ID)
	}

	existing, err := p.agents.Get(ctx, defaults.Namespace, agentName)
	if err == nil && existing != nil {
		if agentReferencesSkill(existing, p.namespace, skillName) {
			return agentName, nil
		}
		existing.SkillPolicy.Skills = append(existing.SkillPolicy.Skills, entity.SkillRef{
			Namespace: p.namespace,
			Name:      skillName,
			Version:   skillVersion,
		})
		existing.AgentCard.Skills = append(existing.AgentCard.Skills, agentSkillFor(target, skillName))
		if _, err := p.agents.Update(ctx, existing); err != nil {
			return "", fmt.Errorf("attach skill %s to agent %s: %w", skillName, agentName, err)
		}
		p.logger.Info("attached generated skill to existing agent",
			"agent", agentName, "skill", skillName, "target", target.ID)
		return agentName, nil
	}
	if err != nil && !domain.IsNotFound(err) {
		return "", fmt.Errorf("look up agent %s: %w", agentName, err)
	}

	container := &entity.AgentContainer{
		Name:      agentName,
		Namespace: defaults.Namespace,
		DACType:   "skill",
		AgentCard: entity.AgentCard{
			Name:        agentCardName(target),
			Description: agentDescription(target),
			Skills:      []entity.AgentSkill{agentSkillFor(target, skillName)},
		},
		SkillPolicy: entity.SkillPolicy{
			Skills: []entity.SkillRef{{
				Namespace: p.namespace,
				Name:      skillName,
				Version:   skillVersion,
			}},
		},
		Model: entity.ModelSpec{
			ExpertLLM:  defaults.ExpertLLM,
			PlannerLLM: defaults.PlannerLLM,
		},
		ExpertAgentMaxSteps:       defaults.ExpertAgentMaxSteps,
		OrchestratorAgentMaxLoops: defaults.OrchestratorAgentMaxLoops,
	}

	if _, err := p.agents.Create(ctx, container); err != nil {
		if domain.IsAlreadyExists(err) {
			// Raced with another refresh; the agent is there, which is the goal.
			return agentName, nil
		}
		return "", fmt.Errorf("create agent %s: %w", agentName, err)
	}

	p.logger.Info("created skill agent for pipeline target",
		"agent", agentName, "namespace", defaults.Namespace,
		"skill", skillName, "target", target.ID, "gateway", target.GatewayURL)
	return agentName, nil
}

// AgentNameForTarget follows the existing convention: <slug>-tdb-agent.
func AgentNameForTarget(target domain.TDBPipelineTarget) string {
	slug := slugify(target.ID)
	if slug == "" {
		slug = slugify(target.Domain)
	}
	if slug == "" {
		return ""
	}
	return slug + "-tdb-agent"
}

// agentCardName title-cases the slug, matching History-TDB-Agent.
func agentCardName(target domain.TDBPipelineTarget) string {
	slug := slugify(target.ID)
	if slug == "" {
		slug = slugify(target.Domain)
	}
	parts := strings.Split(slug, "-")
	for i, part := range parts {
		if part == "" {
			continue
		}
		parts[i] = strings.ToUpper(part[:1]) + part[1:]
	}
	return strings.Join(parts, "-") + "-TDB-Agent"
}

func agentDescription(target domain.TDBPipelineTarget) string {
	subject := target.Label
	if strings.TrimSpace(subject) == "" {
		subject = strings.ReplaceAll(target.Domain, "_", " ")
	}
	return fmt.Sprintf(
		"Answer %s questions grounded in the TDB gateway at %s (domain %q), using wiki, ontology, statements/provenance and search for an evidence-backed answer. Created by DAC Data Management from pipeline target %q.",
		subject,
		strings.TrimPrefix(strings.TrimPrefix(target.GatewayURL, "http://"), "https://"),
		target.Domain,
		target.ID,
	)
}

func agentSkillFor(target domain.TDBPipelineTarget, skillName string) entity.AgentSkill {
	return entity.AgentSkill{
		ID:          skillName,
		Name:        skillName,
		Description: agentDescription(target),
		Tags:        []string{},
		Examples:    []string{},
	}
}

func agentReferencesSkill(container *entity.AgentContainer, namespace, skillName string) bool {
	for _, ref := range container.SkillPolicy.Skills {
		if ref.Name == skillName && (ref.Namespace == namespace || ref.Namespace == "") {
			return true
		}
	}
	return false
}
