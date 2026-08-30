// Package tdbpipeline is the HTTP client for the TDB pipeline controller, the
// asynchronous job API that ingests Markdown sources into a TDB gateway.
//
// The controller runs outside DAC (namespace tdb-pipeline on the fw-worker
// cluster). It owns run execution; DAC owns the submission form, the caller
// identity, and the list of runs DAC has submitted -- the controller has no
// list endpoint, which is why runs are also recorded in DAC's own database.
package tdbpipeline

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/bytedance/sonic"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// maxErrorBodyBytes caps how much of a controller error body is read back.
const maxErrorBodyBytes = 8 << 10

// Client calls the TDB pipeline controller on behalf of one DAC caller identity.
type Client struct {
	baseURL  string
	callerID string
	token    string
	http     *http.Client
	logger   *slog.Logger
}

// NewClient builds a controller client. callerID and token are the credentials
// the controller allowlists; every mutating call carries them.
func NewClient(baseURL, callerID, token string, timeout time.Duration, logger *slog.Logger) *Client {
	if logger == nil {
		logger = slog.Default()
	}
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &Client{
		baseURL:  strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		callerID: strings.TrimSpace(callerID),
		token:    strings.TrimSpace(token),
		http:     &http.Client{Timeout: timeout},
		logger:   logger,
	}
}

// CreateRun submits a new pipeline run. idempotencyKey must be stable for a
// given (source, target) pair: the controller returns the original run for a
// repeated key and 409 for the same key with a different body.
func (c *Client) CreateRun(ctx context.Context, req *domain.CreateTDBPipelineRunRequest, idempotencyKey string) (*domain.TDBPipelineRunAck, error) {
	if req == nil {
		return nil, domain.NewInvalidInputError("pipeline run request is required")
	}
	if strings.TrimSpace(idempotencyKey) == "" {
		return nil, domain.NewInvalidInputError("idempotency key is required")
	}

	body := createRunWire{
		Source: sourceWire{
			Type:      req.Source.Type,
			URI:       req.Source.URI,
			ClaimName: req.Source.ClaimName,
			Path:      req.Source.Path,
		},
		Collection: req.Collection,
		Image:      req.Image,
		Target: targetWire{
			GatewayURL:      req.Target.GatewayURL,
			Domain:          req.Target.Domain,
			KnowledgeDomain: req.Target.KnowledgeDomain,
			DomainProfile:   req.Target.DomainProfile,
		},
		Options: toOptionsWire(req.Options),
		ArtifactUpload: artifactUploadWire{
			RunsPrefix:          req.ArtifactUpload.RunsPrefix,
			StatusPrefix:        req.ArtifactUpload.StatusPrefix,
			AttemptStatusPrefix: req.ArtifactUpload.AttemptStatusPrefix,
			Strict:              req.ArtifactUpload.Strict,
		},
		Callback: toCallbackWire(req.Callback),
		Metadata: req.Metadata,
	}

	var ack createRunAckWire
	err := c.do(ctx, http.MethodPost, "/v1/pipeline-runs", map[string]string{
		"Idempotency-Key": idempotencyKey,
	}, body, &ack)
	if err != nil {
		return nil, err
	}
	if strings.TrimSpace(ack.RunID) == "" {
		return nil, domain.NewInternalError(fmt.Errorf("controller returned no runId"))
	}

	return &domain.TDBPipelineRunAck{
		RunID:     ack.RunID,
		Status:    ack.Status,
		StatusURL: ack.StatusURL,
	}, nil
}

// GetRun reads the live run summary. Only the controller-owned fields are set;
// the usecase joins this with DAC's stored record.
func (c *Client) GetRun(ctx context.Context, runID string) (*domain.TDBPipelineRun, error) {
	if strings.TrimSpace(runID) == "" {
		return nil, domain.NewInvalidInputError("run id is required")
	}

	var summary runSummaryWire
	if err := c.do(ctx, http.MethodGet, "/v1/pipeline-runs/"+runID, nil, nil, &summary); err != nil {
		return nil, err
	}

	return &domain.TDBPipelineRun{
		RunID:  summary.RunID,
		Status: summary.Status,
		Counters: domain.TDBPipelineRunCounters{
			TotalJobs: summary.TotalJobs,
			Queued:    summary.Queued,
			Starting:  summary.Starting,
			Running:   summary.Running,
			Uploading: summary.Uploading,
			Succeeded: summary.Succeeded,
			Failed:    summary.Failed,
			Canceled:  summary.Canceled,
		},
	}, nil
}

// Pause stops dispatching queued jobs. Already running jobs keep going.
func (c *Client) Pause(ctx context.Context, runID string) (*domain.TDBPipelineActionResult, error) {
	return c.action(ctx, runID, "pause", nil)
}

// Resume lets queued jobs dispatch again.
func (c *Client) Resume(ctx context.Context, runID string) (*domain.TDBPipelineActionResult, error) {
	return c.action(ctx, runID, "resume", nil)
}

// Cancel marks the run canceled and deletes its active worker Jobs. TDB writes
// already made by completed stages are not rolled back.
func (c *Client) Cancel(ctx context.Context, runID string) (*domain.TDBPipelineActionResult, error) {
	return c.action(ctx, runID, "cancel", nil)
}

// RetryFailed requeues failed jobs for a full pipeline rerun, optionally
// narrowed to one failed stage.
func (c *Client) RetryFailed(ctx context.Context, runID, failedStage string) (*domain.TDBPipelineActionResult, error) {
	stage := strings.TrimSpace(failedStage)
	if stage == domain.TDBPipelineFailedStageS3Upload {
		// The controller answers 400 here. Fail before the round trip so the
		// operator gets the actionable message instead of a generic one.
		return nil, domain.NewInvalidInputError("s3_upload failures must be retried with retry-s3-upload")
	}
	return c.action(ctx, runID, "retry-failed", retryFailedWire{FailedStage: stage})
}

// RetryS3Upload retries only the artifact upload of jobs whose pipeline
// already succeeded.
func (c *Client) RetryS3Upload(ctx context.Context, runID string) (*domain.TDBPipelineActionResult, error) {
	return c.action(ctx, runID, "retry-s3-upload", nil)
}

func (c *Client) action(ctx context.Context, runID, verb string, body any) (*domain.TDBPipelineActionResult, error) {
	if strings.TrimSpace(runID) == "" {
		return nil, domain.NewInvalidInputError("run id is required")
	}

	var result actionResultWire
	path := "/v1/pipeline-runs/" + runID + "/" + verb
	if err := c.do(ctx, http.MethodPost, path, nil, body, &result); err != nil {
		return nil, err
	}

	return &domain.TDBPipelineActionResult{
		RunID:            result.RunID,
		Status:           result.Status,
		DeletedJobs:      result.DeletedJobs,
		RetriedJobs:      result.RetriedJobs,
		RequestedUploads: result.RequestedUploads,
	}, nil
}

// do performs one controller call and decodes its JSON body into out.
func (c *Client) do(ctx context.Context, method, path string, extraHeaders map[string]string, body any, out any) error {
	if c.baseURL == "" {
		return domain.NewInternalError(fmt.Errorf("tdb pipeline controller base URL is empty"))
	}

	var reader io.Reader
	if body != nil {
		encoded, err := sonic.Marshal(body)
		if err != nil {
			return domain.NewInternalError(fmt.Errorf("encode request: %w", err))
		}
		reader = bytes.NewReader(encoded)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return domain.NewInternalError(fmt.Errorf("new request: %w", err))
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.callerID != "" {
		req.Header.Set("X-TDB-Caller-ID", c.callerID)
	}
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	for k, v := range extraHeaders {
		req.Header.Set(k, v)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return domain.NewInternalError(fmt.Errorf("tdb pipeline controller request failed: %w", err))
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return c.statusError(resp)
	}

	if out == nil {
		return nil
	}
	payload, err := io.ReadAll(resp.Body)
	if err != nil {
		return domain.NewInternalError(fmt.Errorf("read response: %w", err))
	}
	if err := sonic.Unmarshal(payload, out); err != nil {
		return domain.NewInternalError(fmt.Errorf("decode response: %w", err))
	}
	return nil
}

// statusError turns a controller error status into the matching domain error.
// The controller's own message is preserved for 4xx because it names which
// allowlist rejected the request, which is what the operator needs to see.
func (c *Client) statusError(resp *http.Response) error {
	message := readErrorMessage(resp)
	c.logger.Warn("tdb pipeline controller returned error",
		"status", resp.StatusCode, "message", message)

	switch resp.StatusCode {
	case http.StatusBadRequest:
		return domain.NewInvalidInputError(message)
	case http.StatusForbidden:
		// Not an auth failure for the DAC user: the controller rejected the
		// caller, image, gateway, domain, profile, LLM profile or callback host
		// against its allowlist. Surface it as bad input on the submitted form.
		return domain.NewInvalidInputError("rejected by controller allowlist: " + message)
	case http.StatusNotFound:
		return domain.NewNotFoundError("pipeline run", message)
	case http.StatusConflict:
		return domain.NewConflictError("idempotency key already used with a different request body")
	default:
		return domain.NewInternalError(fmt.Errorf("controller returned %d: %s", resp.StatusCode, message))
	}
}

func readErrorMessage(resp *http.Response) string {
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxErrorBodyBytes))
	if err != nil || len(raw) == 0 {
		return resp.Status
	}

	var parsed errorWire
	if err := sonic.Unmarshal(raw, &parsed); err == nil {
		if msg := strings.TrimSpace(parsed.Detail); msg != "" {
			return msg
		}
		if msg := strings.TrimSpace(parsed.Message); msg != "" {
			return msg
		}
	}
	if msg := strings.TrimSpace(string(raw)); msg != "" {
		return msg
	}
	return resp.Status
}

func toCallbackWire(callback *domain.TDBPipelineCallback) *callbackWire {
	if callback == nil || strings.TrimSpace(callback.URL) == "" {
		return nil
	}
	return &callbackWire{URL: strings.TrimSpace(callback.URL), Events: callback.Events}
}

func toOptionsWire(opts domain.TDBPipelineOptions) *optionsWire {
	wire := optionsWire{
		LLMProfile:                    strings.TrimSpace(opts.LLMProfile),
		GenerateQA:                    opts.GenerateQA,
		AutoEval:                      opts.AutoEval,
		LLMGrade:                      opts.LLMGrade,
		OpenLayerPredicateMergeEvery:  opts.OpenLayerPredicateMergeEvery,
		OpenLayerPredicateAutopromote: opts.OpenLayerPredicateAutopromote,
		MaxConcurrent:                 opts.MaxConcurrent,
		StartStaggerSeconds:           opts.StartStaggerSeconds,
		StartStaggerJitterSeconds:     opts.StartStaggerJitterSeconds,
		QuestionWorkers:               opts.QuestionWorkers,
		QuestionRepairTimeoutSeconds:  opts.QuestionRepairTimeoutSeconds,
	}
	if wire == (optionsWire{}) {
		// Send no options block at all so the controller applies its defaults.
		return nil
	}
	return &wire
}
