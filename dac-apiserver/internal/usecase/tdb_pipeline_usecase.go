package usecase

import (
	"context"
	"log/slog"
	"strings"
	"sync"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// maxSummaryRefreshConcurrency bounds how many controller summary calls a single
// run listing may issue at once.
const maxSummaryRefreshConcurrency = 8

// terminalRunStatuses never change again, so listing them does not re-read the
// controller.
var terminalRunStatuses = map[string]struct{}{
	"succeeded": {},
	"failed":    {},
	"canceled":  {},
}

type tdbPipelineUsecase struct {
	controller domain.TDBPipelineControllerRepository
	store      domain.TDBPipelineRunStore
	options    domain.TDBPipelineOptionSet
	skills     domain.TDBPipelineSkillProvisioner
	logger     *slog.Logger
}

// NewTDBPipelineUsecase wires the controller client, the run store and the
// deployment's target allowlist together.
// NewTDBPipelineUsecase wires the controller client, the run store, the target
// allowlist and the skill provisioner together. skills may be nil, in which case
// no skill is published when a run finishes.
func NewTDBPipelineUsecase(
	controller domain.TDBPipelineControllerRepository,
	store domain.TDBPipelineRunStore,
	options domain.TDBPipelineOptionSet,
	skills domain.TDBPipelineSkillProvisioner,
	logger *slog.Logger,
) domain.TDBPipelineUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &tdbPipelineUsecase{
		controller: controller,
		store:      store,
		options:    options,
		skills:     skills,
		logger:     logger,
	}
}

// Options returns the targets, images and defaults the create-run form needs.
func (u *tdbPipelineUsecase) Options(_ context.Context) domain.TDBPipelineOptionSet {
	return u.options
}

// CreateRun validates the request against DAC's copy of the controller
// allowlist, submits it, and records the returned run.
//
// Validating here is not a substitute for the controller's own allowlist -- it
// is what turns "403 forbidden" into a message that names the field the
// operator has to fix, before a round trip.
func (u *tdbPipelineUsecase) CreateRun(ctx context.Context, req *domain.CreateTDBPipelineRunRequest, createdBy string) (*domain.TDBPipelineRun, error) {
	if req == nil {
		return nil, domain.NewInvalidInputError("pipeline run request is required")
	}

	target, err := u.resolveTarget(req)
	if err != nil {
		return nil, err
	}
	if err := u.applyDefaults(req); err != nil {
		return nil, err
	}
	if err := validateSource(req.Source); err != nil {
		return nil, err
	}

	idempotencyKey := domain.BuildTDBPipelineIdempotencyKey(req)
	ack, err := u.controller.CreateRun(ctx, req, idempotencyKey)
	if err != nil {
		return nil, err
	}

	run := &domain.TDBPipelineRun{
		RunID:          ack.RunID,
		Status:         ack.Status,
		Collection:     req.Collection,
		SourceType:     req.Source.Type,
		SourceURI:      sourceLocation(req.Source),
		GatewayURL:     req.Target.GatewayURL,
		Domain:         req.Target.Domain,
		DomainProfile:  req.Target.DomainProfile,
		Image:          req.Image,
		LLMProfile:     req.Options.LLMProfile,
		IdempotencyKey: idempotencyKey,
		CreatedBy:      createdBy,
		Metadata:       req.Metadata,
	}

	if err := u.store.Save(ctx, run); err != nil {
		// The run is already accepted by the controller. Losing the local
		// record would strand it -- there is no list endpoint to find it
		// again -- so surface the failure with the run ID in the log.
		u.logger.Error("failed to record submitted pipeline run",
			"error", err, "run_id", run.RunID, "target", target.Domain)
		return nil, err
	}

	return run, nil
}

// GetRun joins DAC's stored record with the controller's live summary.
func (u *tdbPipelineUsecase) GetRun(ctx context.Context, runID string) (*domain.TDBPipelineRun, error) {
	run, err := u.store.Get(ctx, runID)
	if err != nil {
		return nil, err
	}
	u.refresh(ctx, run)
	return run, nil
}

// ListRuns returns DAC's submitted runs, refreshing the ones that can still
// change. Runs whose summary could not be read keep their last known values
// and carry SummaryError.
func (u *tdbPipelineUsecase) ListRuns(ctx context.Context, filter domain.TDBPipelineRunFilter) ([]*domain.TDBPipelineRun, int, error) {
	runs, total, err := u.store.List(ctx, filter)
	if err != nil {
		return nil, 0, err
	}

	var (
		wg   sync.WaitGroup
		slot = make(chan struct{}, maxSummaryRefreshConcurrency)
	)
	for _, run := range runs {
		if isTerminalRunStatus(run.Status) {
			continue
		}
		wg.Add(1)
		slot <- struct{}{}
		go func(r *domain.TDBPipelineRun) {
			defer wg.Done()
			defer func() { <-slot }()
			u.refresh(ctx, r)
		}(run)
	}
	wg.Wait()

	return runs, total, nil
}

func (u *tdbPipelineUsecase) Pause(ctx context.Context, runID string) (*domain.TDBPipelineActionResult, error) {
	return u.act(ctx, runID, u.controller.Pause)
}

func (u *tdbPipelineUsecase) Resume(ctx context.Context, runID string) (*domain.TDBPipelineActionResult, error) {
	return u.act(ctx, runID, u.controller.Resume)
}

func (u *tdbPipelineUsecase) Cancel(ctx context.Context, runID string) (*domain.TDBPipelineActionResult, error) {
	return u.act(ctx, runID, u.controller.Cancel)
}

// RetryFailed requeues failed jobs. An empty failedStage retries all of them.
func (u *tdbPipelineUsecase) RetryFailed(ctx context.Context, runID, failedStage string) (*domain.TDBPipelineActionResult, error) {
	return u.act(ctx, runID, func(ctx context.Context, id string) (*domain.TDBPipelineActionResult, error) {
		return u.controller.RetryFailed(ctx, id, failedStage)
	})
}

func (u *tdbPipelineUsecase) RetryS3Upload(ctx context.Context, runID string) (*domain.TDBPipelineActionResult, error) {
	return u.act(ctx, runID, u.controller.RetryS3Upload)
}

// act runs one control-plane verb and writes the resulting status back to the
// stored record so the run list reflects it immediately.
func (u *tdbPipelineUsecase) act(
	ctx context.Context,
	runID string,
	call func(context.Context, string) (*domain.TDBPipelineActionResult, error),
) (*domain.TDBPipelineActionResult, error) {
	run, err := u.store.Get(ctx, runID)
	if err != nil {
		return nil, err
	}

	result, err := call(ctx, run.RunID)
	if err != nil {
		return nil, err
	}
	if status := strings.TrimSpace(result.Status); status != "" {
		if err := u.store.UpdateSummary(ctx, run.RunID, status, run.Counters); err != nil {
			u.logger.Warn("failed to persist run status after control action",
				"error", err, "run_id", run.RunID, "status", status)
		}
	}
	return result, nil
}

// refresh overlays the controller's live summary onto a stored run.
func (u *tdbPipelineUsecase) refresh(ctx context.Context, run *domain.TDBPipelineRun) {
	summary, err := u.controller.GetRun(ctx, run.RunID)
	if err != nil {
		run.SummaryError = err.Error()
		u.logger.Warn("failed to read pipeline run summary", "error", err, "run_id", run.RunID)
		return
	}

	previousStatus := run.Status
	run.Status = summary.Status
	run.Counters = summary.Counters
	if err := u.store.UpdateSummary(ctx, run.RunID, summary.Status, summary.Counters); err != nil {
		u.logger.Warn("failed to persist pipeline run summary", "error", err, "run_id", run.RunID)
	}

	// Publish the target's skill the first time a run lands content there.
	if !isTerminalRunStatus(previousStatus) && isTerminalRunStatus(run.Status) {
		u.provisionSkill(ctx, run)
	}
}

// provisionSkill publishes the QA skill for a finished run's target, so the
// corpus it just ingested is answerable. Failures are logged, never surfaced:
// the ingestion itself already succeeded, and re-running this recovers it.
func (u *tdbPipelineUsecase) provisionSkill(ctx context.Context, run *domain.TDBPipelineRun) {
	if u.skills == nil {
		return
	}
	if run.Counters.Succeeded == 0 {
		// Nothing was written to the gateway, so there is nothing to answer over.
		return
	}

	target, ok := u.targetForRun(run)
	if !ok {
		u.logger.Warn("no configured target matches finished run; skipping skill publish",
			"run_id", run.RunID, "domain", run.Domain, "gateway", run.GatewayURL)
		return
	}

	name, err := u.skills.EnsureSkill(ctx, target, run.Collection)
	if err != nil {
		u.logger.Error("failed to publish skill for finished run",
			"error", err, "run_id", run.RunID, "target", target.ID)
		return
	}
	if name != "" {
		u.logger.Info("skill available for finished run",
			"run_id", run.RunID, "target", target.ID, "skill", name)
	}
}

// targetForRun finds the configured target a stored run was submitted against.
// The gateway is what identifies it: one domain can have several gateways.
func (u *tdbPipelineUsecase) targetForRun(run *domain.TDBPipelineRun) (domain.TDBPipelineTarget, bool) {
	for _, target := range u.options.Targets {
		if target.GatewayURL == run.GatewayURL && target.Domain == run.Domain {
			return target, true
		}
	}
	return domain.TDBPipelineTarget{}, false
}

// resolveTarget matches the requested domain against the configured targets and
// fills in the gateway and profile the operator did not have to type.
func (u *tdbPipelineUsecase) resolveTarget(req *domain.CreateTDBPipelineRunRequest) (domain.TDBPipelineTarget, error) {
	targetID := strings.TrimSpace(req.Target.TargetID)
	domainLabel := strings.TrimSpace(req.Target.Domain)
	if targetID == "" && domainLabel == "" {
		return domain.TDBPipelineTarget{}, domain.NewInvalidInputError("target.target_id or target.domain is required")
	}

	for _, target := range u.options.Targets {
		if targetID != "" {
			if target.ID != targetID {
				continue
			}
		} else if target.Domain != domainLabel {
			continue
		}
		domainLabel = target.Domain
		req.Target.Domain = domainLabel
		if strings.TrimSpace(req.Target.GatewayURL) == "" {
			req.Target.GatewayURL = target.GatewayURL
		}
		if strings.TrimSpace(req.Target.DomainProfile) == "" {
			req.Target.DomainProfile = target.DomainProfile
		}
		if !u.isAllowedGateway(req.Target.GatewayURL) {
			return domain.TDBPipelineTarget{}, domain.NewInvalidInputError(
				"target.gatewayUrl " + req.Target.GatewayURL + " is not a configured TDB gateway")
		}
		// The controller requires knowledgeDomain == domain.
		req.Target.KnowledgeDomain = domainLabel
		return target, nil
	}

	if targetID != "" {
		return domain.TDBPipelineTarget{}, domain.NewInvalidInputError(
			"target.target_id " + targetID + " is not a configured TDB pipeline target")
	}
	return domain.TDBPipelineTarget{}, domain.NewInvalidInputError(
		"target.domain " + domainLabel + " is not a configured TDB pipeline domain")
}

// applyDefaults fills the fields the deployment, not the operator, decides.
func (u *tdbPipelineUsecase) applyDefaults(req *domain.CreateTDBPipelineRunRequest) error {
	defaults := u.options.Defaults

	if strings.TrimSpace(req.Collection) == "" {
		req.Collection = defaults.Collection
	}
	if strings.TrimSpace(req.Collection) == "" {
		return domain.NewInvalidInputError("collection is required")
	}

	if strings.TrimSpace(req.Image) == "" {
		req.Image = defaults.Image
	}
	if !containsString(u.options.Images, req.Image) {
		return domain.NewInvalidInputError("image " + req.Image + " is not an allowed pipeline image")
	}

	if strings.TrimSpace(req.Options.LLMProfile) == "" {
		req.Options.LLMProfile = defaults.LLMProfile
	}
	if !containsString(u.options.LLMProfiles, req.Options.LLMProfile) {
		return domain.NewInvalidInputError("options.llmProfile must be one of " + strings.Join(u.options.LLMProfiles, ", "))
	}

	if strings.TrimSpace(req.ArtifactUpload.RunsPrefix) == "" {
		req.ArtifactUpload.RunsPrefix = defaults.RunsPrefix
	}
	if strings.TrimSpace(req.ArtifactUpload.StatusPrefix) == "" {
		req.ArtifactUpload.StatusPrefix = defaults.StatusPrefix
	}
	if strings.TrimSpace(req.ArtifactUpload.AttemptStatusPrefix) == "" {
		req.ArtifactUpload.AttemptStatusPrefix = defaults.AttemptStatusPrefix
	}
	if !strings.HasPrefix(req.ArtifactUpload.RunsPrefix, "s3://") {
		return domain.NewInvalidInputError("artifactUpload.runsPrefix must be an s3:// prefix")
	}
	if !strings.HasPrefix(req.ArtifactUpload.StatusPrefix, "s3://") {
		return domain.NewInvalidInputError("artifactUpload.statusPrefix must be an s3:// prefix")
	}
	return nil
}

func (u *tdbPipelineUsecase) isAllowedGateway(gatewayURL string) bool {
	for _, target := range u.options.Targets {
		if target.GatewayURL == gatewayURL {
			return true
		}
	}
	return false
}

func validateSource(source domain.TDBPipelineSource) error {
	switch source.Type {
	case domain.TDBPipelineSourceS3:
		if !strings.HasPrefix(strings.TrimSpace(source.URI), "s3://") {
			return domain.NewInvalidInputError("source.uri must be an s3:// object or prefix")
		}
	case domain.TDBPipelineSourcePVC:
		if strings.TrimSpace(source.ClaimName) == "" {
			return domain.NewInvalidInputError("source.claimName is required for a pvc source")
		}
		if !strings.HasPrefix(strings.TrimSpace(source.Path), "/") {
			return domain.NewInvalidInputError("source.path must be an absolute path inside the pvc")
		}
	default:
		return domain.NewInvalidInputError("source.type must be s3 or pvc")
	}
	return nil
}

func sourceLocation(source domain.TDBPipelineSource) string {
	if source.Type == domain.TDBPipelineSourcePVC {
		return source.ClaimName + ":" + source.Path
	}
	return source.URI
}

func isTerminalRunStatus(status string) bool {
	_, ok := terminalRunStatuses[strings.ToLower(strings.TrimSpace(status))]
	return ok
}

func containsString(values []string, want string) bool {
	for _, v := range values {
		if v == want {
			return true
		}
	}
	return false
}
