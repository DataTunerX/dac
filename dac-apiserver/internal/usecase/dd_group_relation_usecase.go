package usecase

import (
	"context"
	"fmt"
	"log/slog"
	"strings"

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

// Create adds a semantic domain to a semantic group by writing dd_group_relation.
// This is the manual UI path: it does not call semantic-grouper, so description /
// agent_card are left unchanged (callers may edit those separately).
func (u *ddGroupRelationUsecase) Create(ctx context.Context, req *domain.CreateDDGroupRelationRequest) (*domain.DDGroupRelation, error) {
	if req == nil {
		return nil, domain.NewInvalidInputError("empty request")
	}
	sdID := strings.TrimSpace(req.SemanticDomainID)
	groupID := strings.TrimSpace(req.GroupID)
	if sdID == "" {
		return nil, domain.NewInvalidInputError("sd_id is required")
	}
	if groupID == "" {
		return nil, domain.NewInvalidInputError("group_id is required")
	}

	if _, err := u.dsClient.GetSemanticGroup(ctx, groupID); err != nil {
		return nil, err
	}
	if _, err := u.dsClient.GetSemanticDomain(ctx, sdID); err != nil {
		return nil, err
	}

	existing, _, err := u.dsClient.ListDDGroupRelationsByGroup(ctx, groupID)
	if err != nil {
		return nil, err
	}
	for _, rel := range existing {
		if rel.SemanticDomainID == sdID {
			u.logger.Warn("skip duplicate semantic group member", "group_id", groupID, "sd_id", sdID)
			return nil, domain.NewAlreadyExistsError("dd group relation", sdID)
		}
	}

	reason := strings.TrimSpace(req.AssociationReason)
	u.logger.Info("creating dd group relation", "group_id", groupID, "sd_id", sdID)
	created, err := u.dsClient.CreateDDGroupRelation(ctx, map[string]any{
		"sd_id":              sdID,
		"group_id":           groupID,
		"association_reason": reason,
	})
	if err != nil {
		u.logger.Error("create dd group relation failed", "group_id", groupID, "sd_id", sdID, "error", err)
		return nil, err
	}
	if created == nil {
		return nil, domain.NewInternalError(fmt.Errorf("create dd group relation returned empty result"))
	}

	// data-services create may omit the auto-increment id; resolve it from the group listing.
	if created != nil && created.ID == 0 {
		listed, _, listErr := u.dsClient.ListDDGroupRelationsByGroup(ctx, groupID)
		if listErr != nil {
			u.logger.Warn("created relation but failed to reload id", "group_id", groupID, "sd_id", sdID, "error", listErr)
		} else {
			for i := range listed {
				if listed[i].SemanticDomainID == sdID {
					created = &listed[i]
					break
				}
			}
		}
	}

	refreshSemanticGroupVector(ctx, u.dsClient, u.logger, groupID)
	u.logger.Info("dd group relation created", "group_id", groupID, "sd_id", sdID, "relation_id", created.ID)
	return created, nil
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
	u.logger.Info("deleting dd group relation", "relation_id", id)
	if err := u.dsClient.DeleteDDGroupRelationByID(ctx, id); err != nil {
		u.logger.Error("delete dd group relation failed", "relation_id", id, "error", err)
		return err
	}
	u.logger.Info("dd group relation deleted", "relation_id", id)
	return nil
}
