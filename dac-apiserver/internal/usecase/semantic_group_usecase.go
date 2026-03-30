package usecase

import (
	"context"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type semanticGroupUsecase struct {
	dsClient domain.DataServicesClient
	logger   *slog.Logger
}

func NewSemanticGroupUsecase(dsClient domain.DataServicesClient, logger *slog.Logger) domain.SemanticGroupUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &semanticGroupUsecase{
		dsClient: dsClient,
		logger:   logger,
	}
}

func (u *semanticGroupUsecase) Create(ctx context.Context, req *domain.CreateSemanticGroupRequest) (*domain.SemanticGroup, error) {
	if req == nil || req.GroupName == "" {
		return nil, domain.NewInvalidInputError("groupName is required")
	}
	dsReq := map[string]any{
		"group_name":  req.GroupName,
		"description": req.Description,
		"agent_card":  req.AgentCard,
		"version":     req.Version,
	}
	return u.dsClient.CreateSemanticGroup(ctx, dsReq)
}

func (u *semanticGroupUsecase) BatchCreate(ctx context.Context, req []domain.CreateSemanticGroupRequest) (int, error) {
	if len(req) == 0 {
		return 0, domain.NewInvalidInputError("empty request")
	}
	dsReq := make([]map[string]any, 0, len(req))
	for _, r := range req {
		if r.GroupName == "" {
			return 0, domain.NewInvalidInputError("groupName is required")
		}
		dsReq = append(dsReq, map[string]any{
			"group_name":  r.GroupName,
			"description": r.Description,
			"agent_card":  r.AgentCard,
			"version":     r.Version,
		})
	}
	return u.dsClient.BatchCreateSemanticGroups(ctx, dsReq)
}

func (u *semanticGroupUsecase) Get(ctx context.Context, id string) (*domain.SemanticGroup, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.GetSemanticGroup(ctx, id)
}

func (u *semanticGroupUsecase) GetWithMembers(ctx context.Context, id string) (*domain.SemanticGroupWithMembers, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.GetSemanticGroupWithMembers(ctx, id)
}

func (u *semanticGroupUsecase) List(ctx context.Context, limit, offset int) ([]domain.SemanticGroup, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}
	page := offset/limit + 1
	pageSize := limit
	return u.dsClient.ListSemanticGroups(ctx, page, pageSize)
}

func (u *semanticGroupUsecase) ListRoots(ctx context.Context) ([]domain.SemanticGroup, int, error) {
	return u.dsClient.ListSemanticGroupRoots(ctx)
}

func (u *semanticGroupUsecase) Update(ctx context.Context, id string, req *domain.UpdateSemanticGroupRequest) (*domain.SemanticGroup, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	if req == nil {
		return nil, domain.NewInvalidInputError("empty request")
	}
	dsReq := map[string]any{}
	if req.GroupName != nil {
		dsReq["group_name"] = *req.GroupName
	}
	if req.Description != nil {
		dsReq["description"] = *req.Description
	}
	if req.AgentCard != nil {
		dsReq["agent_card"] = *req.AgentCard
	}
	if req.Version != nil {
		dsReq["version"] = *req.Version
	}
	return u.dsClient.UpdateSemanticGroup(ctx, id, dsReq)
}

func (u *semanticGroupUsecase) Delete(ctx context.Context, id string) error {
	if id == "" {
		return domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.DeleteSemanticGroup(ctx, id)
}

func (u *semanticGroupUsecase) Exists(ctx context.Context, id string) (bool, error) {
	if id == "" {
		return false, domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.SemanticGroupExists(ctx, id)
}

func (u *semanticGroupUsecase) Count(ctx context.Context) (int, error) {
	return u.dsClient.SemanticGroupCount(ctx)
}
