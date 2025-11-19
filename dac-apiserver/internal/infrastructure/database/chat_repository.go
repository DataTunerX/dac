package database

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/ent"
	"github.com/lvyanru/dac-apiserver/internal/ent/run"
)

// chatRepository is the database implementation of ChatRepository interface.
// It uses ent ORM to interact with MySQL, managing user and run persistence.
type chatRepository struct {
	client *ent.Client
}

// NewChatRepository creates a new ChatRepository instance.
//
// Parameters:
//   - client: ent database client
//
// Returns:
//   - domain.ChatRepository: Repository interface implementation
func NewChatRepository(client *ent.Client) domain.ChatRepository {
	return &chatRepository{
		client: client,
	}
}

// GetOrCreateRun gets a run by RunID, or creates a new run (new conversation) if it doesn't exist.
//
// Behavior:
//   - If runID is empty: creates a new run (starts a new conversation)
//   - If runID exists: returns existing run (continues same conversation)
//
// Parameters:
//   - ctx: request context
//   - userID: user UUID string
//   - runID: run UUID string (can be empty)
//   - agentID: Agent ID (can be empty)
//
// Returns:
//   - *entity.Run: run entity
//   - error: UUID format error or database operation failure
func (r *chatRepository) GetOrCreateRun(ctx context.Context, userID, runID, agentID string) (*entity.Run, error) {
	uid, err := uuid.Parse(userID)
	if err != nil {
		return nil, fmt.Errorf("invalid user id: %w", err)
	}

	// If runID is provided, try to get it
	if runID != "" {
		rid, err := uuid.Parse(runID)
		if err != nil {
			return nil, fmt.Errorf("invalid run id: %w", err)
		}

		runEntity, err := r.client.Run.Query().
			Where(
				run.ID(rid),
				run.UserID(uid),
			).
			Only(ctx)

		if err == nil {
			return toRunEntity(runEntity), nil
		}

		if !ent.IsNotFound(err) {
			return nil, err
		}
	}

	// Create new run
	created, err := r.client.Run.Create().
		SetUserID(uid).
		SetAgentID(agentID).
		Save(ctx)
	if err != nil {
		return nil, err
	}
	return toRunEntity(created), nil
}

// GetRun gets run by ID
func (r *chatRepository) GetRun(ctx context.Context, runID string) (*entity.Run, error) {
	rid, err := uuid.Parse(runID)
	if err != nil {
		return nil, fmt.Errorf("invalid run id: %w", err)
	}

	runEntity, err := r.client.Run.Get(ctx, rid)
	if err != nil {
		if ent.IsNotFound(err) {
			return nil, domain.NewNotFoundError("run", runID)
		}
		return nil, err
	}

	return toRunEntity(runEntity), nil
}

// ListUserRuns gets all runs for user
func (r *chatRepository) ListUserRuns(ctx context.Context, userID string) ([]*entity.Run, error) {
	uid, err := uuid.Parse(userID)
	if err != nil {
		return nil, fmt.Errorf("invalid user id: %w", err)
	}

	runs, err := r.client.Run.Query().
		Where(run.UserID(uid)).
		Order(ent.Desc(run.FieldCreatedAt)).
		All(ctx)
	if err != nil {
		return nil, err
	}

	// Convert to domain entity
	result := make([]*entity.Run, len(runs))
	for i, r := range runs {
		result[i] = toRunEntity(r)
	}
	return result, nil
}

// DeleteRun deletes run
func (r *chatRepository) DeleteRun(ctx context.Context, runID string) error {
	rid, err := uuid.Parse(runID)
	if err != nil {
		return fmt.Errorf("invalid run id: %w", err)
	}

	err = r.client.Run.DeleteOneID(rid).Exec(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			return domain.NewNotFoundError("run", runID)
		}
		return err
	}

	return nil
}
