package tdbpipeline

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/bytedance/sonic"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// runsTable holds DAC's record of every run it has submitted. The controller
// exposes only GET /v1/pipeline-runs/{runId} -- there is no list endpoint --
// so without this table DAC could not render a run list or recover a run ID
// after the submitting session ended.
const runsTable = "tdb_pipeline_runs"

const createRunsTableSQL = "CREATE TABLE IF NOT EXISTS " + runsTable + " (\n" +
	"  `run_id` VARCHAR(128) NOT NULL COMMENT 'Controller run ID',\n" +
	"  `status` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'Last known run status',\n" +
	"  `collection` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Logical collection name',\n" +
	"  `source_type` VARCHAR(16) NOT NULL DEFAULT '' COMMENT 's3 or pvc',\n" +
	"  `source_uri` VARCHAR(1024) NOT NULL DEFAULT '' COMMENT 's3 URI, or claim/path for pvc',\n" +
	"  `gateway_url` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Target TDB gateway',\n" +
	"  `domain` VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'Target domain label',\n" +
	"  `domain_profile` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Profile path inside the pipeline image',\n" +
	"  `image` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'Pipeline worker image',\n" +
	"  `llm_profile` VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'local or openai',\n" +
	"  `idempotency_key` VARCHAR(512) NOT NULL DEFAULT '' COMMENT 'Key sent to the controller',\n" +
	"  `created_by` VARCHAR(128) NOT NULL DEFAULT '' COMMENT 'DAC user who submitted the run',\n" +
	"  `total_jobs` INT NOT NULL DEFAULT 0,\n" +
	"  `queued` INT NOT NULL DEFAULT 0,\n" +
	"  `starting` INT NOT NULL DEFAULT 0,\n" +
	"  `running` INT NOT NULL DEFAULT 0,\n" +
	"  `uploading` INT NOT NULL DEFAULT 0,\n" +
	"  `succeeded` INT NOT NULL DEFAULT 0,\n" +
	"  `failed` INT NOT NULL DEFAULT 0,\n" +
	"  `canceled` INT NOT NULL DEFAULT 0,\n" +
	"  `metadata` TEXT NULL COMMENT 'Free-form metadata submitted with the run',\n" +
	"  `created_at` DATETIME NOT NULL,\n" +
	"  `updated_at` DATETIME NOT NULL,\n" +
	"  PRIMARY KEY (`run_id`),\n" +
	"  KEY `idx_tdb_pipeline_runs_domain` (`domain`),\n" +
	"  KEY `idx_tdb_pipeline_runs_status` (`status`),\n" +
	"  KEY `idx_tdb_pipeline_runs_created_at` (`created_at`)\n" +
	") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"

const runColumns = "`run_id`, `status`, `collection`, `source_type`, `source_uri`, `gateway_url`, " +
	"`domain`, `domain_profile`, `image`, `llm_profile`, `idempotency_key`, `created_by`, " +
	"`total_jobs`, `queued`, `starting`, `running`, `uploading`, `succeeded`, `failed`, `canceled`, " +
	"`metadata`, `created_at`, `updated_at`"

// Store persists DAC's submitted runs in the apiserver's MySQL database.
type Store struct {
	db     *sql.DB
	logger *slog.Logger
}

// NewStore creates the run table if it is missing and returns the store.
func NewStore(ctx context.Context, db *sql.DB, logger *slog.Logger) (*Store, error) {
	if db == nil {
		return nil, fmt.Errorf("tdb pipeline store requires a database handle")
	}
	if logger == nil {
		logger = slog.Default()
	}
	if _, err := db.ExecContext(ctx, createRunsTableSQL); err != nil {
		return nil, fmt.Errorf("create %s table: %w", runsTable, err)
	}
	return &Store{db: db, logger: logger}, nil
}

// Save records a submitted run, or refreshes it when the controller returned an
// existing run for a repeated idempotency key.
func (s *Store) Save(ctx context.Context, run *domain.TDBPipelineRun) error {
	if run == nil || strings.TrimSpace(run.RunID) == "" {
		return domain.NewInvalidInputError("run id is required")
	}

	metadata, err := encodeMetadata(run.Metadata)
	if err != nil {
		return domain.NewInternalError(err)
	}

	now := time.Now()
	if run.CreatedAt.IsZero() {
		run.CreatedAt = now
	}
	run.UpdatedAt = now

	query := "INSERT INTO " + runsTable + " (" + runColumns + ") VALUES (" +
		strings.TrimSuffix(strings.Repeat("?, ", 23), ", ") + ") " +
		"ON DUPLICATE KEY UPDATE `status` = VALUES(`status`), `total_jobs` = VALUES(`total_jobs`), " +
		"`queued` = VALUES(`queued`), `starting` = VALUES(`starting`), `running` = VALUES(`running`), " +
		"`uploading` = VALUES(`uploading`), `succeeded` = VALUES(`succeeded`), `failed` = VALUES(`failed`), " +
		"`canceled` = VALUES(`canceled`), `updated_at` = VALUES(`updated_at`)"

	_, err = s.db.ExecContext(ctx, query,
		run.RunID, run.Status, run.Collection, run.SourceType, run.SourceURI, run.GatewayURL,
		run.Domain, run.DomainProfile, run.Image, run.LLMProfile, run.IdempotencyKey, run.CreatedBy,
		run.Counters.TotalJobs, run.Counters.Queued, run.Counters.Starting, run.Counters.Running,
		run.Counters.Uploading, run.Counters.Succeeded, run.Counters.Failed, run.Counters.Canceled,
		metadata, run.CreatedAt, run.UpdatedAt,
	)
	if err != nil {
		return domain.NewInternalError(fmt.Errorf("save pipeline run: %w", err))
	}
	return nil
}

// UpdateSummary writes back the status and counters read from the controller.
func (s *Store) UpdateSummary(ctx context.Context, runID, status string, counters domain.TDBPipelineRunCounters) error {
	if strings.TrimSpace(runID) == "" {
		return domain.NewInvalidInputError("run id is required")
	}

	query := "UPDATE " + runsTable + " SET `status` = ?, `total_jobs` = ?, `queued` = ?, `starting` = ?, " +
		"`running` = ?, `uploading` = ?, `succeeded` = ?, `failed` = ?, `canceled` = ?, `updated_at` = ? " +
		"WHERE `run_id` = ?"

	_, err := s.db.ExecContext(ctx, query,
		status, counters.TotalJobs, counters.Queued, counters.Starting, counters.Running,
		counters.Uploading, counters.Succeeded, counters.Failed, counters.Canceled, time.Now(), runID,
	)
	if err != nil {
		return domain.NewInternalError(fmt.Errorf("update pipeline run summary: %w", err))
	}
	return nil
}

// Get reads one stored run.
func (s *Store) Get(ctx context.Context, runID string) (*domain.TDBPipelineRun, error) {
	if strings.TrimSpace(runID) == "" {
		return nil, domain.NewInvalidInputError("run id is required")
	}

	row := s.db.QueryRowContext(ctx, "SELECT "+runColumns+" FROM "+runsTable+" WHERE `run_id` = ?", runID)
	run, err := scanRun(row)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, domain.NewNotFoundError("pipeline run", runID)
		}
		return nil, domain.NewInternalError(fmt.Errorf("get pipeline run: %w", err))
	}
	return run, nil
}

// List returns stored runs newest first, plus the total matching the filter.
func (s *Store) List(ctx context.Context, filter domain.TDBPipelineRunFilter) ([]*domain.TDBPipelineRun, int, error) {
	where := make([]string, 0, 2)
	args := make([]any, 0, 2)
	if domainLabel := strings.TrimSpace(filter.Domain); domainLabel != "" {
		where = append(where, "`domain` = ?")
		args = append(args, domainLabel)
	}
	if status := strings.TrimSpace(filter.Status); status != "" {
		where = append(where, "`status` = ?")
		args = append(args, status)
	}
	clause := ""
	if len(where) > 0 {
		clause = " WHERE " + strings.Join(where, " AND ")
	}

	var total int
	if err := s.db.QueryRowContext(ctx, "SELECT COUNT(*) FROM "+runsTable+clause, args...).Scan(&total); err != nil {
		return nil, 0, domain.NewInternalError(fmt.Errorf("count pipeline runs: %w", err))
	}

	limit := filter.Limit
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	offset := filter.Offset
	if offset < 0 {
		offset = 0
	}

	query := "SELECT " + runColumns + " FROM " + runsTable + clause + " ORDER BY `created_at` DESC LIMIT ? OFFSET ?"
	rows, err := s.db.QueryContext(ctx, query, append(args, limit, offset)...)
	if err != nil {
		return nil, 0, domain.NewInternalError(fmt.Errorf("list pipeline runs: %w", err))
	}
	defer rows.Close()

	runs := make([]*domain.TDBPipelineRun, 0, limit)
	for rows.Next() {
		run, err := scanRun(rows)
		if err != nil {
			return nil, 0, domain.NewInternalError(fmt.Errorf("scan pipeline run: %w", err))
		}
		runs = append(runs, run)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, domain.NewInternalError(fmt.Errorf("iterate pipeline runs: %w", err))
	}
	return runs, total, nil
}

// rowScanner is satisfied by both *sql.Row and *sql.Rows.
type rowScanner interface {
	Scan(dest ...any) error
}

func scanRun(row rowScanner) (*domain.TDBPipelineRun, error) {
	var (
		run      domain.TDBPipelineRun
		metadata sql.NullString
	)
	err := row.Scan(
		&run.RunID, &run.Status, &run.Collection, &run.SourceType, &run.SourceURI, &run.GatewayURL,
		&run.Domain, &run.DomainProfile, &run.Image, &run.LLMProfile, &run.IdempotencyKey, &run.CreatedBy,
		&run.Counters.TotalJobs, &run.Counters.Queued, &run.Counters.Starting, &run.Counters.Running,
		&run.Counters.Uploading, &run.Counters.Succeeded, &run.Counters.Failed, &run.Counters.Canceled,
		&metadata, &run.CreatedAt, &run.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	if metadata.Valid && strings.TrimSpace(metadata.String) != "" {
		decoded := map[string]any{}
		if err := sonic.Unmarshal([]byte(metadata.String), &decoded); err == nil {
			run.Metadata = decoded
		}
	}
	return &run, nil
}

func encodeMetadata(metadata map[string]any) (sql.NullString, error) {
	if len(metadata) == 0 {
		return sql.NullString{}, nil
	}
	encoded, err := sonic.Marshal(metadata)
	if err != nil {
		return sql.NullString{}, fmt.Errorf("encode run metadata: %w", err)
	}
	return sql.NullString{String: string(encoded), Valid: true}, nil
}
