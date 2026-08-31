package dto

import (
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// TDB pipeline DTOs use DAC's snake_case API style. The controller's own
// camelCase contract is confined to the tdbpipeline infrastructure package.

type TDBPipelineSourceRequest struct {
	Type      string `json:"type"`
	URI       string `json:"uri"`
	ClaimName string `json:"claim_name"`
	Path      string `json:"path"`
}

type TDBPipelineTargetRequest struct {
	TargetID      string `json:"target_id"`
	Domain        string `json:"domain"`
	GatewayURL    string `json:"gateway_url"`
	DomainProfile string `json:"domain_profile"`
}

type TDBPipelineOptionsRequest struct {
	LLMProfile                    string `json:"llm_profile"`
	GenerateQA                    *bool  `json:"generate_qa"`
	AutoEval                      *bool  `json:"auto_eval"`
	LLMGrade                      *bool  `json:"llm_grade"`
	OpenLayerPredicateMergeEvery  *int   `json:"open_layer_predicate_merge_every"`
	OpenLayerPredicateAutopromote *bool  `json:"open_layer_predicate_autopromote"`
	MaxConcurrent                 *int   `json:"max_concurrent"`
	StartStaggerSeconds           *int   `json:"start_stagger_seconds"`
	StartStaggerJitterSeconds     *int   `json:"start_stagger_jitter_seconds"`
	QuestionWorkers               *int   `json:"question_workers"`
	QuestionRepairTimeoutSeconds  *int   `json:"question_repair_timeout_seconds"`
}

type TDBPipelineArtifactUploadRequest struct {
	RunsPrefix          string `json:"runs_prefix"`
	StatusPrefix        string `json:"status_prefix"`
	AttemptStatusPrefix string `json:"attempt_status_prefix"`
	Strict              *bool  `json:"strict"`
}

// CreateTDBPipelineRunRequest is the create-run body the UI submits. Everything
// except source and target may be omitted; the deployment’s defaults fill
// the rest.
type TDBPipelineCallbackRequest struct {
	URL    string   `json:"url"`
	Events []string `json:"events"`
}

type CreateTDBPipelineRunRequest struct {
	Source         TDBPipelineSourceRequest         `json:"source"`
	Target         TDBPipelineTargetRequest         `json:"target"`
	Collection     string                           `json:"collection"`
	Image          string                           `json:"image"`
	Options        TDBPipelineOptionsRequest        `json:"options"`
	ArtifactUpload TDBPipelineArtifactUploadRequest `json:"artifact_upload"`
	Callback       *TDBPipelineCallbackRequest      `json:"callback"`
	Metadata       map[string]any                   `json:"metadata"`
	DatasetID      string                           `json:"dataset_id"`
	SourceVersion  string                           `json:"source_version"`
	IdempotencyKey string                           `json:"idempotency_key"`
}

type RetryTDBPipelineFailedRequest struct {
	FailedStage string `json:"failed_stage"`
}

type TDBPipelineTargetResponse struct {
	ID            string `json:"id"`
	Domain        string `json:"domain"`
	Label         string `json:"label"`
	GatewayURL    string `json:"gateway_url"`
	DomainProfile string `json:"domain_profile"`
	Collection    string `json:"collection"`
	SkillAgent    string `json:"skill_agent,omitempty"`
	Test          bool   `json:"test"`
}

type TDBPipelineDefaultsResponse struct {
	Collection          string `json:"collection"`
	Image               string `json:"image"`
	LLMProfile          string `json:"llm_profile"`
	RunsPrefix          string `json:"runs_prefix"`
	StatusPrefix        string `json:"status_prefix"`
	AttemptStatusPrefix string `json:"attempt_status_prefix"`
}

type TDBPipelineOptionsResponse struct {
	Targets     []TDBPipelineTargetResponse `json:"targets"`
	Images      []string                    `json:"images"`
	LLMProfiles []string                    `json:"llm_profiles"`
	Defaults    TDBPipelineDefaultsResponse `json:"defaults"`
}

type TDBPipelineCountersResponse struct {
	TotalJobs int `json:"total_jobs"`
	Queued    int `json:"queued"`
	Starting  int `json:"starting"`
	Running   int `json:"running"`
	Uploading int `json:"uploading"`
	Succeeded int `json:"succeeded"`
	Failed    int `json:"failed"`
	Canceled  int `json:"canceled"`
}

type TDBPipelineRunResponse struct {
	RunID          string                      `json:"run_id"`
	Status         string                      `json:"status"`
	Collection     string                      `json:"collection"`
	SourceType     string                      `json:"source_type"`
	SourceURI      string                      `json:"source_uri"`
	GatewayURL     string                      `json:"gateway_url"`
	Domain         string                      `json:"domain"`
	DomainProfile  string                      `json:"domain_profile"`
	Image          string                      `json:"image"`
	LLMProfile     string                      `json:"llm_profile"`
	IdempotencyKey string                      `json:"idempotency_key"`
	CreatedBy      string                      `json:"created_by"`
	CreatedAt      time.Time                   `json:"created_at"`
	UpdatedAt      time.Time                   `json:"updated_at"`
	Counters       TDBPipelineCountersResponse `json:"counters"`
	Metadata       map[string]any              `json:"metadata,omitempty"`
	SummaryError   string                      `json:"summary_error,omitempty"`
}

type TDBPipelineActionResponse struct {
	RunID            string   `json:"run_id"`
	Status           string   `json:"status"`
	DeletedJobs      []string `json:"deleted_jobs,omitempty"`
	RetriedJobs      int      `json:"retried_jobs,omitempty"`
	RequestedUploads int      `json:"requested_uploads,omitempty"`
}

// ToDomainCreateTDBPipelineRunRequest converts the API body into the domain
// request. Validation of targets, images and prefixes belongs to the usecase.
func ToDomainCreateTDBPipelineRunRequest(req *CreateTDBPipelineRunRequest) *domain.CreateTDBPipelineRunRequest {
	if req == nil {
		return nil
	}
	return &domain.CreateTDBPipelineRunRequest{
		Source: domain.TDBPipelineSource{
			Type:      req.Source.Type,
			URI:       req.Source.URI,
			ClaimName: req.Source.ClaimName,
			Path:      req.Source.Path,
		},
		Collection: req.Collection,
		Image:      req.Image,
		Target: domain.TDBPipelineTargetSpec{
			TargetID:      req.Target.TargetID,
			GatewayURL:    req.Target.GatewayURL,
			Domain:        req.Target.Domain,
			DomainProfile: req.Target.DomainProfile,
		},
		Options: domain.TDBPipelineOptions{
			LLMProfile:                    req.Options.LLMProfile,
			GenerateQA:                    req.Options.GenerateQA,
			AutoEval:                      req.Options.AutoEval,
			LLMGrade:                      req.Options.LLMGrade,
			OpenLayerPredicateMergeEvery:  req.Options.OpenLayerPredicateMergeEvery,
			OpenLayerPredicateAutopromote: req.Options.OpenLayerPredicateAutopromote,
			MaxConcurrent:                 req.Options.MaxConcurrent,
			StartStaggerSeconds:           req.Options.StartStaggerSeconds,
			StartStaggerJitterSeconds:     req.Options.StartStaggerJitterSeconds,
			QuestionWorkers:               req.Options.QuestionWorkers,
			QuestionRepairTimeoutSeconds:  req.Options.QuestionRepairTimeoutSeconds,
		},
		ArtifactUpload: domain.TDBPipelineArtifactUpload{
			RunsPrefix:          req.ArtifactUpload.RunsPrefix,
			StatusPrefix:        req.ArtifactUpload.StatusPrefix,
			AttemptStatusPrefix: req.ArtifactUpload.AttemptStatusPrefix,
			Strict:              req.ArtifactUpload.Strict,
		},
		Callback:       toDomainTDBPipelineCallback(req.Callback),
		Metadata:       req.Metadata,
		DatasetID:      req.DatasetID,
		SourceVersion:  req.SourceVersion,
		IdempotencyKey: req.IdempotencyKey,
	}
}

func toDomainTDBPipelineCallback(callback *TDBPipelineCallbackRequest) *domain.TDBPipelineCallback {
	if callback == nil || callback.URL == "" {
		return nil
	}
	return &domain.TDBPipelineCallback{URL: callback.URL, Events: callback.Events}
}

func ToTDBPipelineOptionsResponse(options domain.TDBPipelineOptionSet) TDBPipelineOptionsResponse {
	targets := make([]TDBPipelineTargetResponse, 0, len(options.Targets))
	for _, target := range options.Targets {
		targets = append(targets, TDBPipelineTargetResponse{
			ID:            target.ID,
			Domain:        target.Domain,
			Label:         target.Label,
			GatewayURL:    target.GatewayURL,
			DomainProfile: target.DomainProfile,
			Collection:    target.Collection,
			SkillAgent:    target.SkillAgent,
			Test:          target.Test,
		})
	}
	return TDBPipelineOptionsResponse{
		Targets:     targets,
		Images:      options.Images,
		LLMProfiles: options.LLMProfiles,
		Defaults: TDBPipelineDefaultsResponse{
			Collection:          options.Defaults.Collection,
			Image:               options.Defaults.Image,
			LLMProfile:          options.Defaults.LLMProfile,
			RunsPrefix:          options.Defaults.RunsPrefix,
			StatusPrefix:        options.Defaults.StatusPrefix,
			AttemptStatusPrefix: options.Defaults.AttemptStatusPrefix,
		},
	}
}

func ToTDBPipelineRunResponse(run *domain.TDBPipelineRun) TDBPipelineRunResponse {
	if run == nil {
		return TDBPipelineRunResponse{}
	}
	return TDBPipelineRunResponse{
		RunID:          run.RunID,
		Status:         run.Status,
		Collection:     run.Collection,
		SourceType:     run.SourceType,
		SourceURI:      run.SourceURI,
		GatewayURL:     run.GatewayURL,
		Domain:         run.Domain,
		DomainProfile:  run.DomainProfile,
		Image:          run.Image,
		LLMProfile:     run.LLMProfile,
		IdempotencyKey: run.IdempotencyKey,
		CreatedBy:      run.CreatedBy,
		CreatedAt:      run.CreatedAt,
		UpdatedAt:      run.UpdatedAt,
		Counters: TDBPipelineCountersResponse{
			TotalJobs: run.Counters.TotalJobs,
			Queued:    run.Counters.Queued,
			Starting:  run.Counters.Starting,
			Running:   run.Counters.Running,
			Uploading: run.Counters.Uploading,
			Succeeded: run.Counters.Succeeded,
			Failed:    run.Counters.Failed,
			Canceled:  run.Counters.Canceled,
		},
		Metadata:     run.Metadata,
		SummaryError: run.SummaryError,
	}
}

func ToTDBPipelineActionResponse(result *domain.TDBPipelineActionResult) TDBPipelineActionResponse {
	if result == nil {
		return TDBPipelineActionResponse{}
	}
	return TDBPipelineActionResponse{
		RunID:            result.RunID,
		Status:           result.Status,
		DeletedJobs:      result.DeletedJobs,
		RetriedJobs:      result.RetriedJobs,
		RequestedUploads: result.RequestedUploads,
	}
}
