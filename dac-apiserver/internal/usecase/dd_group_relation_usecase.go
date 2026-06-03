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
