package usecase

import (
	"context"
	"errors"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/dataservices"
)

type semanticGroupUsecase struct {
	dsClient *dataservices.Client
	logger   *slog.Logger
}

func NewSemanticGroupUsecase(dsClient *dataservices.Client, logger *slog.Logger) domain.SemanticGroupUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &semanticGroupUsecase{
		dsClient: dsClient,
		logger:   logger,
	}
}

func (u *semanticGroupUsecase) Create(ctx context.Context, req *domain.CreateSemanticGroupRequest) (*dataservices.SemanticGroup, error) {
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

func (u *semanticGroupUsecase) Get(ctx context.Context, id string) (*dataservices.SemanticGroup, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	g, err := u.dsClient.GetSemanticGroup(ctx, id)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return nil, domain.NewNotFoundError("semantic group", id)
		}
		return nil, err
	}
	return g, nil
}

func (u *semanticGroupUsecase) List(ctx context.Context, limit, offset int) ([]dataservices.SemanticGroup, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}
	page := offset/limit + 1
	pageSize := limit
	items, total, err := u.dsClient.ListSemanticGroups(ctx, page, pageSize)
	if err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

func (u *semanticGroupUsecase) Update(ctx context.Context, id string, req *domain.UpdateSemanticGroupRequest) (*dataservices.SemanticGroup, error) {
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
	g, err := u.dsClient.UpdateSemanticGroup(ctx, id, dsReq)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return nil, domain.NewNotFoundError("semantic group", id)
		}
		return nil, err
	}
	return g, nil
}

func (u *semanticGroupUsecase) Delete(ctx context.Context, id string) error {
	if id == "" {
		return domain.NewInvalidInputError("id is required")
	}
	err := u.dsClient.DeleteSemanticGroup(ctx, id)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return domain.NewNotFoundError("semantic group", id)
		}
		return err
	}
	return nil
}

func (u *semanticGroupUsecase) Exists(ctx context.Context, id string) (bool, error) {
	if id == "" {
		return false, domain.NewInvalidInputError("id is required")
	}
	ok, err := u.dsClient.SemanticGroupExists(ctx, id)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return false, nil
		}
		return false, err
	}
	return ok, nil
}

func (u *semanticGroupUsecase) Count(ctx context.Context) (int, error) {
	return u.dsClient.SemanticGroupCount(ctx)
}
