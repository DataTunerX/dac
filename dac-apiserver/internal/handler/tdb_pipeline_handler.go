package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// TDBPipelineHandler exposes the TDB pipeline controller to DAC Data
// Management: submit an ingestion run, watch it, and pause/cancel/retry it.
type TDBPipelineHandler struct {
	usecase domain.TDBPipelineUsecase
	logger  *slog.Logger
}

func NewTDBPipelineHandler(uc domain.TDBPipelineUsecase, logger *slog.Logger) *TDBPipelineHandler {
	if logger == nil {
		logger = slog.Default()
	}
	return &TDBPipelineHandler{usecase: uc, logger: logger}
}

// Options returns the targets, images and defaults the create-run form needs.
//
//	@Summary		Get TDB pipeline form options
//	@Description	List allowlisted TDB targets, pipeline images and submission defaults
//	@Tags			TDBPipeline
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200	{object}	map[string]any
//	@Router			/tdb-pipeline/options [get]
func (h *TDBPipelineHandler) Options(ctx context.Context, c *app.RequestContext) {
	SuccessResponse(c, dto.ToTDBPipelineOptionsResponse(h.usecase.Options(ctx)))
}

// CreateRun submits a pipeline ingestion run.
//
//	@Summary		Create a TDB pipeline run
//	@Description	Submit a source for ingestion into a TDB gateway
//	@Tags			TDBPipeline
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			request	body		dto.CreateTDBPipelineRunRequest	true	"Run request"
//	@Success		202		{object}	map[string]any
//	@Router			/tdb-pipeline/runs [post]
func (h *TDBPipelineHandler) CreateRun(ctx context.Context, c *app.RequestContext) {
	userID, ok := GetUserIDFromContext(c, h.logger)
	if !ok {
		ErrorResponse(c, domain.ErrUnauthorized)
		return
	}

	var req dto.CreateTDBPipelineRunRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	run, err := h.usecase.CreateRun(ctx, dto.ToDomainCreateTDBPipelineRunRequest(&req), userID)
	if err != nil {
		h.logger.Error("failed to create tdb pipeline run", "error", err, "domain", req.Target.Domain)
		ErrorResponse(c, err)
		return
	}

	// The controller accepted the run; jobs are dispatched asynchronously.
	AcceptedResponse(c, dto.ToTDBPipelineRunResponse(run))
}

// ListRuns lists the runs DAC has submitted.
//
//	@Summary		List TDB pipeline runs
//	@Description	List submitted runs with their latest controller status
//	@Tags			TDBPipeline
//	@Produce		json
//	@Security		BearerAuth
//	@Param			domain	query		string	false	"Filter by target domain"
//	@Param			status	query		string	false	"Filter by run status"
//	@Success		200		{object}	map[string]any
//	@Router			/tdb-pipeline/runs [get]
func (h *TDBPipelineHandler) ListRuns(ctx context.Context, c *app.RequestContext) {
	page := parseLimitOffset(c, 50, 200)
	filter := domain.TDBPipelineRunFilter{
		Domain: c.Query("domain"),
		Status: c.Query("status"),
		Limit:  page.Limit,
		Offset: page.Offset,
	}

	runs, total, err := h.usecase.ListRuns(ctx, filter)
	if err != nil {
		h.logger.Error("failed to list tdb pipeline runs", "error", err)
		ErrorResponse(c, err)
		return
	}

	items := make([]dto.TDBPipelineRunResponse, 0, len(runs))
	for _, run := range runs {
		items = append(items, dto.ToTDBPipelineRunResponse(run))
	}
	SuccessResponse(c, map[string]any{"items": items, "totalCount": total})
}

// GetRun returns one run with a freshly read controller summary.
//
//	@Summary		Get a TDB pipeline run
//	@Description	Get one run's status and per-job counters
//	@Tags			TDBPipeline
//	@Produce		json
//	@Security		BearerAuth
//	@Param			runId	path		string	true	"Run ID"
//	@Success		200		{object}	map[string]any
//	@Router			/tdb-pipeline/runs/{runId} [get]
func (h *TDBPipelineHandler) GetRun(ctx context.Context, c *app.RequestContext) {
	run, err := h.usecase.GetRun(ctx, c.Param("runId"))
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToTDBPipelineRunResponse(run))
}

// Pause stops dispatching queued jobs.
//
//	@Summary		Pause a TDB pipeline run
//	@Tags			TDBPipeline
//	@Produce		json
//	@Security		BearerAuth
//	@Param			runId	path		string	true	"Run ID"
//	@Success		200		{object}	map[string]any
//	@Router			/tdb-pipeline/runs/{runId}/pause [post]
func (h *TDBPipelineHandler) Pause(ctx context.Context, c *app.RequestContext) {
	h.respondAction(ctx, c, "pause", h.usecase.Pause)
}

// Resume lets queued jobs dispatch again.
//
//	@Summary		Resume a TDB pipeline run
//	@Tags			TDBPipeline
//	@Produce		json
//	@Security		BearerAuth
//	@Param			runId	path		string	true	"Run ID"
//	@Success		200		{object}	map[string]any
//	@Router			/tdb-pipeline/runs/{runId}/resume [post]
func (h *TDBPipelineHandler) Resume(ctx context.Context, c *app.RequestContext) {
	h.respondAction(ctx, c, "resume", h.usecase.Resume)
}

// Cancel cancels the run and deletes its active worker Jobs.
//
//	@Summary		Cancel a TDB pipeline run
//	@Description	Cancel the run; TDB writes already made are not rolled back
//	@Tags			TDBPipeline
//	@Produce		json
//	@Security		BearerAuth
//	@Param			runId	path		string	true	"Run ID"
//	@Success		200		{object}	map[string]any
//	@Router			/tdb-pipeline/runs/{runId}/cancel [post]
func (h *TDBPipelineHandler) Cancel(ctx context.Context, c *app.RequestContext) {
	h.respondAction(ctx, c, "cancel", h.usecase.Cancel)
}

// RetryFailed requeues failed jobs for a full rerun.
//
//	@Summary		Retry failed jobs of a TDB pipeline run
//	@Description	Requeue failed jobs, optionally only those that failed at one stage
//	@Tags			TDBPipeline
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			runId	path		string								true	"Run ID"
//	@Param			request	body		dto.RetryTDBPipelineFailedRequest	false	"Stage filter"
//	@Success		200		{object}	map[string]any
//	@Router			/tdb-pipeline/runs/{runId}/retry-failed [post]
func (h *TDBPipelineHandler) RetryFailed(ctx context.Context, c *app.RequestContext) {
	// The body is optional: an empty request retries every failed job.
	var req dto.RetryTDBPipelineFailedRequest
	if len(c.Request.Body()) > 0 {
		if err := c.BindJSON(&req); err != nil {
			ErrorResponse(c, domain.ErrInvalidInput)
			return
		}
	}

	result, err := h.usecase.RetryFailed(ctx, c.Param("runId"), req.FailedStage)
	if err != nil {
		h.logger.Error("failed to retry tdb pipeline run", "error", err, "run_id", c.Param("runId"))
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToTDBPipelineActionResponse(result))
}

// RetryS3Upload retries only the artifact upload of already-succeeded jobs.
//
//	@Summary		Retry artifact upload of a TDB pipeline run
//	@Description	Retry S3 upload without rerunning ingestion
//	@Tags			TDBPipeline
//	@Produce		json
//	@Security		BearerAuth
//	@Param			runId	path		string	true	"Run ID"
//	@Success		200		{object}	map[string]any
//	@Router			/tdb-pipeline/runs/{runId}/retry-s3-upload [post]
func (h *TDBPipelineHandler) RetryS3Upload(ctx context.Context, c *app.RequestContext) {
	h.respondAction(ctx, c, "retry-s3-upload", h.usecase.RetryS3Upload)
}

func (h *TDBPipelineHandler) respondAction(
	ctx context.Context,
	c *app.RequestContext,
	verb string,
	call func(context.Context, string) (*domain.TDBPipelineActionResult, error),
) {
	runID := c.Param("runId")
	result, err := call(ctx, runID)
	if err != nil {
		h.logger.Error("tdb pipeline control action failed", "error", err, "action", verb, "run_id", runID)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToTDBPipelineActionResponse(result))
}
