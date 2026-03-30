package usecase

import (
	"context"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type semanticDomainUsecase struct {
	dsClient domain.DataServicesClient
	logger   *slog.Logger
}

func NewSemanticDomainUsecase(dsClient domain.DataServicesClient, logger *slog.Logger) domain.SemanticDomainUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &semanticDomainUsecase{
		dsClient: dsClient,
		logger:   logger,
	}
}

func (u *semanticDomainUsecase) Create(ctx context.Context, req *domain.CreateSemanticDomainRequest) (*domain.SemanticDomain, error) {
	if req == nil || req.SemanticDomain == "" || req.DDNamespace == "" || req.DDName == "" {
		return nil, domain.NewInvalidInputError("semantic_domain, dd_namespace and dd_name are required")
	}
	dsReq := map[string]any{
		"semantic_domain": req.SemanticDomain,
		"agent_card":      req.AgentCard,
		"dd_namespace":    req.DDNamespace,
		"dd_name":         req.DDName,
	}
	return u.dsClient.CreateSemanticDomain(ctx, dsReq)
}

func (u *semanticDomainUsecase) BatchCreate(ctx context.Context, req []domain.CreateSemanticDomainRequest) (int, error) {
	if len(req) == 0 {
		return 0, domain.NewInvalidInputError("empty request")
	}
	dsReq := make([]map[string]any, 0, len(req))
	for _, r := range req {
		if r.SemanticDomain == "" || r.DDNamespace == "" || r.DDName == "" {
			return 0, domain.NewInvalidInputError("semantic_domain, dd_namespace and dd_name are required")
		}
		dsReq = append(dsReq, map[string]any{
			"semantic_domain": r.SemanticDomain,
			"agent_card":      r.AgentCard,
			"dd_namespace":    r.DDNamespace,
			"dd_name":         r.DDName,
		})
	}
	return u.dsClient.BatchCreateSemanticDomains(ctx, dsReq)
}

func (u *semanticDomainUsecase) Get(ctx context.Context, id string) (*domain.SemanticDomain, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.GetSemanticDomain(ctx, id)
}

func (u *semanticDomainUsecase) SearchByDD(ctx context.Context, req *domain.SearchSemanticDomainByDDRequest) ([]domain.SemanticDomain, int, error) {
	if req == nil || req.DDNamespace == "" || req.DDName == "" {
		return nil, 0, domain.NewInvalidInputError("dd_namespace and dd_name are required")
	}
	return u.dsClient.SearchSemanticDomainsByDD(ctx, req.DDNamespace, req.DDName)
}

func (u *semanticDomainUsecase) Update(ctx context.Context, id string, req *domain.UpdateSemanticDomainRequest) (*domain.SemanticDomain, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	if req == nil {
		return nil, domain.NewInvalidInputError("empty request")
	}
	dsReq := map[string]any{}
	if req.SemanticDomain != nil {
		dsReq["semantic_domain"] = *req.SemanticDomain
	}
	if req.AgentCard != nil {
		dsReq["agent_card"] = *req.AgentCard
	}
	if req.DDNamespace != nil {
		dsReq["dd_namespace"] = *req.DDNamespace
	}
	if req.DDName != nil {
		dsReq["dd_name"] = *req.DDName
	}
	return u.dsClient.UpdateSemanticDomain(ctx, id, dsReq)
}

func (u *semanticDomainUsecase) Delete(ctx context.Context, id string) error {
	if id == "" {
		return domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.DeleteSemanticDomain(ctx, id)
}

func (u *semanticDomainUsecase) DeleteByDDInfo(ctx context.Context, ddNamespace, ddName string) error {
	if ddNamespace == "" || ddName == "" {
		return domain.NewInvalidInputError("dd_namespace and dd_name are required")
	}
	return u.dsClient.DeleteSemanticDomainByDDInfo(ctx, ddNamespace, ddName)
}

func (u *semanticDomainUsecase) Exists(ctx context.Context, id string) (bool, error) {
	if id == "" {
		return false, domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.SemanticDomainExists(ctx, id)
}

func (u *semanticDomainUsecase) ExistsByDDInfo(ctx context.Context, ddNamespace, ddName string) (bool, error) {
	if ddNamespace == "" || ddName == "" {
		return false, domain.NewInvalidInputError("dd_namespace and dd_name are required")
	}
	return u.dsClient.SemanticDomainExistsByDDInfo(ctx, ddNamespace, ddName)
}

func (u *semanticDomainUsecase) Count(ctx context.Context) (int, error) {
	return u.dsClient.SemanticDomainCount(ctx)
}
