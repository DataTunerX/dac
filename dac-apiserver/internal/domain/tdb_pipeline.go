package domain

import (
	"context"
	"strings"
	"time"
)

// TDB pipeline source types accepted by the controller.
const (
	TDBPipelineSourceS3  = "s3"
	TDBPipelineSourcePVC = "pvc"
)

// TDB pipeline LLM profiles accepted by the controller.
const (
	TDBPipelineLLMProfileLocal  = "local"
	TDBPipelineLLMProfileOpenAI = "openai"
)

// TDBPipelineFailedStageS3Upload is the one failed stage that must be retried
// through retry-s3-upload; the controller rejects it on retry-failed with 400.
const TDBPipelineFailedStageS3Upload = "s3_upload"

// TDBPipelineTarget is one selectable TDB target for the create-run form.
// Targets mirror the controller's domain-config allowlist; the controller has
// no endpoint that exposes it, so DAC carries its own copy in config.
type TDBPipelineTarget struct {
	// ID uniquely names this target. It is not the domain: the same domain can
	// be pointed at more than one gateway, e.g. archeology at the live gateway
	// the skill agent reads and archeology at the isolated paper test gateway.
	ID string
	// Domain is the controller domain label, e.g. "archeology".
	Domain string
	// Label is the human-readable name shown in the UI.
	Label string
	// GatewayURL is the TDB gateway that receives writes. For domains that a
	// skill agent also queries, this is that same gateway.
	GatewayURL string
	// DomainProfile is the profile path inside the pipeline image.
	DomainProfile string
	// SkillAgent names the skill that reads this gateway, when one exists.
	SkillAgent string
	// Test marks isolated test targets that hold no production content.
	Test bool
}

// TDBPipelineOptionSet is everything the create-run form needs to populate
// itself: allowlisted targets and images plus the deployment's defaults.
type TDBPipelineOptionSet struct {
	Targets     []TDBPipelineTarget
	Images      []string
	LLMProfiles []string
	Defaults    TDBPipelineDefaults
}

// TDBPipelineDefaults are the artifact destinations and option values DAC
// pre-fills so an operator only has to pick a source and a target.
type TDBPipelineDefaults struct {
	Collection          string
	Image               string
	LLMProfile          string
	RunsPrefix          string
	StatusPrefix        string
	AttemptStatusPrefix string
}

// TDBPipelineSource is where the pipeline reads Markdown from.
type TDBPipelineSource struct {
	Type string
	// URI is the s3:// object or prefix, for Type == s3.
	URI string
	// ClaimName and Path locate a directory on a source PVC, for Type == pvc.
	ClaimName string
	Path      string
}

// TDBPipelineTargetSpec selects the gateway/domain/profile a run writes to.
type TDBPipelineTargetSpec struct {
	// TargetID selects a configured target. When empty, Domain is matched
	// against the configured targets instead.
	TargetID        string
	GatewayURL      string
	Domain          string
	KnowledgeDomain string
	DomainProfile   string
}

// TDBPipelineOptions are the pipeline behaviour knobs. Pointer fields are
// omitted from the controller request when nil so the controller's own
// defaults apply.
type TDBPipelineOptions struct {
	LLMProfile                    string
	GenerateQA                    *bool
	AutoEval                      *bool
	LLMGrade                      *bool
	OpenLayerPredicateMergeEvery  *int
	OpenLayerPredicateAutopromote *bool
	MaxConcurrent                 *int
	StartStaggerSeconds           *int
	StartStaggerJitterSeconds     *int
	QuestionWorkers               *int
	QuestionRepairTimeoutSeconds  *int
}

// TDBPipelineCallback asks the controller to post run events back to DAC.
// The controller's callback host allowlist is fail-closed: an un-allowlisted
// host is rejected with 403 at submit time.
type TDBPipelineCallback struct {
	URL string
	// Events filters which events fire. Empty means all callback-capable events.
	Events []string
}

// TDBPipelineArtifactUpload are the S3 destinations for run and status artifacts.
type TDBPipelineArtifactUpload struct {
	RunsPrefix          string
	StatusPrefix        string
	AttemptStatusPrefix string
	Strict              *bool
}

// CreateTDBPipelineRunRequest is a DAC request to ingest a source into a TDB.
type CreateTDBPipelineRunRequest struct {
	Source         TDBPipelineSource
	Collection     string
	Image          string
	Target         TDBPipelineTargetSpec
	Options        TDBPipelineOptions
	ArtifactUpload TDBPipelineArtifactUpload
	// Callback is optional; nil means DAC polls for status instead.
	Callback *TDBPipelineCallback
	Metadata map[string]any

	// DatasetID and SourceVersion feed the idempotency key. Both are optional;
	// see BuildTDBPipelineIdempotencyKey.
	DatasetID     string
	SourceVersion string
	// IdempotencyKey overrides the derived key when the caller wants to force
	// a fresh run over an unchanged source.
	IdempotencyKey string
}

// TDBPipelineRunCounters are the per-job tallies the controller reports.
type TDBPipelineRunCounters struct {
	TotalJobs int
	Queued    int
	Starting  int
	Running   int
	Uploading int
	Succeeded int
	Failed    int
	Canceled  int
}

// TDBPipelineRun is DAC's record of a submitted run, joined with the latest
// summary read back from the controller.
type TDBPipelineRun struct {
	RunID          string
	Status         string
	Collection     string
	SourceType     string
	SourceURI      string
	GatewayURL     string
	Domain         string
	DomainProfile  string
	Image          string
	LLMProfile     string
	IdempotencyKey string
	CreatedBy      string
	CreatedAt      time.Time
	UpdatedAt      time.Time
	Counters       TDBPipelineRunCounters
	Metadata       map[string]any
	// SummaryError is set when the controller could not be reached for a
	// live summary. The stored record is still returned.
	SummaryError string
}

// TDBPipelineRunAck is the controller's response to a create call.
type TDBPipelineRunAck struct {
	RunID     string
	Status    string
	StatusURL string
}

// TDBPipelineActionResult is the controller's response to pause, resume,
// cancel, retry-failed and retry-s3-upload.
type TDBPipelineActionResult struct {
	RunID            string
	Status           string
	DeletedJobs      []string
	RetriedJobs      int
	RequestedUploads int
}

// TDBPipelineRunFilter narrows a run listing.
type TDBPipelineRunFilter struct {
	Domain string
	Status string
	Limit  int
	Offset int
}

// TDBPipelineControllerRepository talks to the TDB pipeline controller API.
type TDBPipelineControllerRepository interface {
	CreateRun(ctx context.Context, req *CreateTDBPipelineRunRequest, idempotencyKey string) (*TDBPipelineRunAck, error)
	GetRun(ctx context.Context, runID string) (*TDBPipelineRun, error)
	Pause(ctx context.Context, runID string) (*TDBPipelineActionResult, error)
	Resume(ctx context.Context, runID string) (*TDBPipelineActionResult, error)
	Cancel(ctx context.Context, runID string) (*TDBPipelineActionResult, error)
	RetryFailed(ctx context.Context, runID, failedStage string) (*TDBPipelineActionResult, error)
	RetryS3Upload(ctx context.Context, runID string) (*TDBPipelineActionResult, error)
}

// TDBPipelineRunStore persists DAC's own record of submitted runs. The
// controller exposes no list endpoint, so this is what backs the run list.
type TDBPipelineRunStore interface {
	Save(ctx context.Context, run *TDBPipelineRun) error
	UpdateSummary(ctx context.Context, runID, status string, counters TDBPipelineRunCounters) error
	Get(ctx context.Context, runID string) (*TDBPipelineRun, error)
	List(ctx context.Context, filter TDBPipelineRunFilter) ([]*TDBPipelineRun, int, error)
}

// TDBPipelineSkillProvisioner publishes the TDB QA skill that answers over a
// pipeline target's gateway, so an ingested corpus becomes queryable without
// anyone hand-writing and uploading a skill. Implementations must be idempotent:
// it is called on every run that reaches a successful terminal state.
type TDBPipelineSkillProvisioner interface {
	EnsureSkill(ctx context.Context, target TDBPipelineTarget, collection string) (string, error)
	// EnsureAgent creates (or extends) the skill agent that loads skillName.
	// Publishing a skill only makes it available: agents load skills from an
	// explicit list, so without this nothing reads the newly ingested corpus.
	EnsureAgent(ctx context.Context, target TDBPipelineTarget, skillName string) (string, error)
}

// TDBPipelineUsecase is the DAC-facing pipeline ingestion API.
type TDBPipelineUsecase interface {
	Options(ctx context.Context) TDBPipelineOptionSet
	CreateRun(ctx context.Context, req *CreateTDBPipelineRunRequest, createdBy string) (*TDBPipelineRun, error)
	GetRun(ctx context.Context, runID string) (*TDBPipelineRun, error)
	ListRuns(ctx context.Context, filter TDBPipelineRunFilter) ([]*TDBPipelineRun, int, error)
	Pause(ctx context.Context, runID string) (*TDBPipelineActionResult, error)
	Resume(ctx context.Context, runID string) (*TDBPipelineActionResult, error)
	Cancel(ctx context.Context, runID string) (*TDBPipelineActionResult, error)
	RetryFailed(ctx context.Context, runID, failedStage string) (*TDBPipelineActionResult, error)
	RetryS3Upload(ctx context.Context, runID string) (*TDBPipelineActionResult, error)
}

// BuildTDBPipelineIdempotencyKey derives the controller idempotency key the
// runbook recommends: <dataset-id>:<source-version>:<domain>:<collection>.
//
// The key is deterministic on purpose. Submitting the same source at the same
// target twice returns the original run instead of ingesting it again; a
// changed source is expected to carry a new sourceVersion (an object ETag or a
// dataset revision). An explicit req.IdempotencyKey wins over the derived one.
func BuildTDBPipelineIdempotencyKey(req *CreateTDBPipelineRunRequest) string {
	if req == nil {
		return ""
	}
	if key := strings.TrimSpace(req.IdempotencyKey); key != "" {
		return key
	}

	dataset := strings.TrimSpace(req.DatasetID)
	if dataset == "" {
		dataset = tdbPipelineSourceIdentity(req.Source)
	}

	version := strings.TrimSpace(req.SourceVersion)
	if version == "" {
		version = "v0"
	}

	return strings.Join([]string{
		tdbPipelineKeySegment(dataset),
		tdbPipelineKeySegment(version),
		tdbPipelineKeySegment(req.Target.Domain),
		tdbPipelineKeySegment(req.Collection),
	}, ":")
}

// tdbPipelineSourceIdentity names a source when the caller gave no dataset ID.
func tdbPipelineSourceIdentity(source TDBPipelineSource) string {
	if source.Type == TDBPipelineSourcePVC {
		return source.ClaimName + "/" + source.Path
	}
	return strings.TrimPrefix(source.URI, "s3://")
}

// tdbPipelineKeySegment reduces one segment to characters that survive a
// header value, and keeps ":" out so segments cannot run together.
func tdbPipelineKeySegment(raw string) string {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "-"
	}
	var b strings.Builder
	b.Grow(len(trimmed))
	for _, r := range trimmed {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9':
			b.WriteRune(r)
		case r == '-' || r == '_' || r == '.' || r == '/':
			b.WriteRune(r)
		default:
			b.WriteRune('-')
		}
	}
	return b.String()
}
