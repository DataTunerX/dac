package usecase

import (
	"context"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type ddGroupRelationUsecase struct {
	dsClient domain.DataServicesClient
	logger   *slog.Logger
}

func NewDDGroupRelationUsecase(dsClient domain.DataServicesClient, logger *slog.Logger) domain.DDGroupRelationUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &ddGroupRelationUsecase{
		dsClient: dsClient,
		logger:   logger,
	}
}

func (u *ddGroupRelationUsecase) Create(ctx context.Context, req *domain.CreateDDGroupRelationRequest) (*domain.DDGroupRelation, error) {
	if req == nil || req.SemanticDomainID == "" || req.GroupID == "" {
		return nil, domain.NewInvalidInputError("sd_id and group_id are required")
	}
	dsReq := map[string]any{
		"sd_id":              req.SemanticDomainID,
		"group_id":           req.GroupID,
		"association_reason": req.AssociationReason,
	}
	return u.dsClient.CreateDDGroupRelation(ctx, dsReq)
}

func (u *ddGroupRelationUsecase) BatchCreate(ctx context.Context, req []domain.CreateDDGroupRelationRequest) (int, error) {
	if len(req) == 0 {
		return 0, domain.NewInvalidInputError("empty request")
	}
	dsReq := make([]map[string]any, 0, len(req))
	for _, r := range req {
		if r.SemanticDomainID == "" || r.GroupID == "" {
			return 0, domain.NewInvalidInputError("sd_id and group_id are required")
		}
		dsReq = append(dsReq, map[string]any{
			"sd_id":              r.SemanticDomainID,
			"group_id":           r.GroupID,
			"association_reason": r.AssociationReason,
		})
	}
	return u.dsClient.BatchCreateDDGroupRelations(ctx, dsReq)
}

func (u *ddGroupRelationUsecase) ListByGroup(ctx context.Context, groupID string) ([]domain.DDGroupRelation, int, error) {
	if groupID == "" {
		return nil, 0, domain.NewInvalidInputError("group_id is required")
	}
	return u.dsClient.ListDDGroupRelationsByGroup(ctx, groupID)
}

func (u *ddGroupRelationUsecase) ListBySemanticDomain(ctx context.Context, semanticDomainID string) ([]domain.DDGroupRelation, int, error) {
	if semanticDomainID == "" {
		return nil, 0, domain.NewInvalidInputError("sd_id is required")
	}
	return u.dsClient.ListDDGroupRelationsBySD(ctx, semanticDomainID)
}

func (u *ddGroupRelationUsecase) DeleteByID(ctx context.Context, id int64) error {
	if id <= 0 {
		return domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.DeleteDDGroupRelationByID(ctx, id)
}

func (u *ddGroupRelationUsecase) DeleteByGroup(ctx context.Context, groupID string) error {
	if groupID == "" {
		return domain.NewInvalidInputError("group_id is required")
	}
	return u.dsClient.DeleteDDGroupRelationsByGroup(ctx, groupID)
}

func (u *ddGroupRelationUsecase) DeleteBySemanticDomain(ctx context.Context, semanticDomainID string) error {
	if semanticDomainID == "" {
		return domain.NewInvalidInputError("sd_id is required")
	}
	return u.dsClient.DeleteDDGroupRelationsBySD(ctx, semanticDomainID)
}
