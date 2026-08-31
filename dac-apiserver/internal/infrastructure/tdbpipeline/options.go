package tdbpipeline

import (
	"github.com/lvyanru/dac-apiserver/internal/config"
	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// OptionSetFromConfig converts the deployment's TDB pipeline configuration into
// the option set the create-run form and the request validation both read.
//
// DAC keeps its own copy of the controller's target allowlist because the
// controller has no endpoint that exposes it. A target whose gateway is missing
// here cannot be selected in DAC even if the controller would accept it, and a
// target listed here that the controller does not allow fails at submit time
// with the controller's own 403 message.
func OptionSetFromConfig(cfg config.TDBPipelineConfig) domain.TDBPipelineOptionSet {
	targets := make([]domain.TDBPipelineTarget, 0, len(cfg.Targets))
	for _, target := range cfg.Targets {
		id := target.ID
		if id == "" {
			id = target.Domain
		}
		label := target.Label
		if label == "" {
			label = target.Domain
		}
		targets = append(targets, domain.TDBPipelineTarget{
			ID:            id,
			Domain:        target.Domain,
			Label:         label,
			GatewayURL:    target.GatewayURL,
			DomainProfile: target.DomainProfile,
			Collection:    target.Collection,
			SkillAgent:    target.SkillAgent,
			Test:          target.Test,
		})
	}

	llmProfiles := cfg.LLMProfiles
	if len(llmProfiles) == 0 {
		llmProfiles = []string{domain.TDBPipelineLLMProfileLocal, domain.TDBPipelineLLMProfileOpenAI}
	}

	return domain.TDBPipelineOptionSet{
		Targets:     targets,
		Images:      cfg.Images,
		LLMProfiles: llmProfiles,
		Defaults: domain.TDBPipelineDefaults{
			Collection:          cfg.Defaults.Collection,
			Image:               cfg.Defaults.Image,
			LLMProfile:          cfg.Defaults.LLMProfile,
			RunsPrefix:          cfg.Defaults.RunsPrefix,
			StatusPrefix:        cfg.Defaults.StatusPrefix,
			AttemptStatusPrefix: cfg.Defaults.AttemptStatusPrefix,
		},
	}
}
