package usecase

import (
	"context"
	"errors"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/dataservices"
)

type semanticDomainUsecase struct {
	dsClient *dataservices.Client
	logger   *slog.Logger
}

func NewSemanticDomainUsecase(dsClient *dataservices.Client, logger *slog.Logger) domain.SemanticDomainUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &semanticDomainUsecase{
		dsClient: dsClient,
		logger:   logger,
	}
}

func (u *semanticDomainUsecase) Create(ctx context.Context, req *domain.CreateSemanticDomainRequest) (*dataservices.SemanticDomain, error) {
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

func (u *semanticDomainUsecase) Get(ctx context.Context, id string) (*dataservices.SemanticDomain, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	sd, err := u.dsClient.GetSemanticDomain(ctx, id)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return nil, domain.NewNotFoundError("semantic domain", id)
		}
		return nil, err
	}
	return sd, nil
}

func (u *semanticDomainUsecase) SearchByDD(ctx context.Context, req *domain.SearchSemanticDomainByDDRequest) ([]dataservices.SemanticDomain, int, error) {
	if req == nil || req.DDNamespace == "" || req.DDName == "" {
		return nil, 0, domain.NewInvalidInputError("dd_namespace and dd_name are required")
	}
	items, total, err := u.dsClient.SearchSemanticDomainsByDD(ctx, req.DDNamespace, req.DDName)
	if err != nil {
		return nil, 0, err
	}
	return items, total, nil
}

func (u *semanticDomainUsecase) Update(ctx context.Context, id string, req *domain.UpdateSemanticDomainRequest) (*dataservices.SemanticDomain, error) {
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
	sd, err := u.dsClient.UpdateSemanticDomain(ctx, id, dsReq)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return nil, domain.NewNotFoundError("semantic domain", id)
		}
		return nil, err
	}
	return sd, nil
}

func (u *semanticDomainUsecase) Delete(ctx context.Context, id string) error {
	if id == "" {
		return domain.NewInvalidInputError("id is required")
	}
	err := u.dsClient.DeleteSemanticDomain(ctx, id)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return domain.NewNotFoundError("semantic domain", id)
		}
		return err
	}
	return nil
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
	ok, err := u.dsClient.SemanticDomainExists(ctx, id)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return false, nil
		}
		return false, err
	}
	return ok, nil
}

func (u *semanticDomainUsecase) ExistsByDDInfo(ctx context.Context, ddNamespace, ddName string) (bool, error) {
	if ddNamespace == "" || ddName == "" {
		return false, domain.NewInvalidInputError("dd_namespace and dd_name are required")
	}
	ok, err := u.dsClient.SemanticDomainExistsByDDInfo(ctx, ddNamespace, ddName)
	if err != nil {
		var httpErr *dataservices.HTTPError
		if errors.As(err, &httpErr) && httpErr.StatusCode == 404 {
			return false, nil
		}
		return false, err
	}
	return ok, nil
}

func (u *semanticDomainUsecase) Count(ctx context.Context) (int, error) {
	return u.dsClient.SemanticDomainCount(ctx)
}
