package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

type SemanticDomainHandler struct {
	usecase domain.SemanticDomainUsecase
	logger  *slog.Logger
}

func NewSemanticDomainHandler(uc domain.SemanticDomainUsecase, logger *slog.Logger) *SemanticDomainHandler {
	if logger == nil {
		logger = slog.Default()
	}
	return &SemanticDomainHandler{usecase: uc, logger: logger}
}

func (h *SemanticDomainHandler) Create(ctx context.Context, c *app.RequestContext) {
	var req dto.CreateSemanticDomainRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	created, err := h.usecase.Create(ctx, &domain.CreateSemanticDomainRequest{
		SemanticDomain: req.SemanticDomain,
		AgentCard:      req.AgentCard,
		DDNamespace:    req.DDNamespace,
		DDName:         req.DDName,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	CreatedResponse(c, created)
}

func (h *SemanticDomainHandler) BatchCreate(ctx context.Context, c *app.RequestContext) {
	var req []dto.CreateSemanticDomainRequest
	if err := c.BindJSON(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	domainReq := make([]domain.CreateSemanticDomainRequest, 0, len(req))
	for _, r := range req {
		domainReq = append(domainReq, domain.CreateSemanticDomainRequest{
			SemanticDomain: r.SemanticDomain,
			AgentCard:      r.AgentCard,
			DDNamespace:    r.DDNamespace,
			DDName:         r.DDName,
		})
	}
	n, err := h.usecase.BatchCreate(ctx, domainReq)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"count": n})
}

// Get returns a semantic domain by id.
func (h *SemanticDomainHandler) Get(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	sd, err := h.usecase.Get(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, sd)
}

func (h *SemanticDomainHandler) SearchByDD(ctx context.Context, c *app.RequestContext) {
	var req dto.SearchSemanticDomainByDDRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	items, total, err := h.usecase.SearchByDD(ctx, &domain.SearchSemanticDomainByDDRequest{
		DDNamespace: req.DDNamespace,
		DDName:      req.DDName,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"items": items, "totalCount": total})
}

func (h *SemanticDomainHandler) Update(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	var req dto.UpdateSemanticDomainRequest
	if err := c.BindJSON(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	updated, err := h.usecase.Update(ctx, id, &domain.UpdateSemanticDomainRequest{
		SemanticDomain: req.SemanticDomain,
		AgentCard:      req.AgentCard,
		DDNamespace:    req.DDNamespace,
		DDName:         req.DDName,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, updated)
}

func (h *SemanticDomainHandler) Delete(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	if err := h.usecase.Delete(ctx, id); err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"message": "semantic domain deleted successfully"})
}

func (h *SemanticDomainHandler) DeleteByDDInfo(ctx context.Context, c *app.RequestContext) {
	ddNamespace := c.Param("dd_namespace")
	ddName := c.Param("dd_name")
	if err := h.usecase.DeleteByDDInfo(ctx, ddNamespace, ddName); err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"message": "semantic domain deleted successfully"})
}

func (h *SemanticDomainHandler) Exists(ctx context.Context, c *app.RequestContext) {
	id := c.Param("id")
	ok, err := h.usecase.Exists(ctx, id)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"exists": ok})
}

func (h *SemanticDomainHandler) ExistsByDDInfo(ctx context.Context, c *app.RequestContext) {
	ddNamespace := c.Param("dd_namespace")
	ddName := c.Param("dd_name")
	ok, err := h.usecase.ExistsByDDInfo(ctx, ddNamespace, ddName)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"exists": ok})
}

func (h *SemanticDomainHandler) Count(ctx context.Context, c *app.RequestContext) {
	n, err := h.usecase.Count(ctx)
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"totalCount": n})
}
