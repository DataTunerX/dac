package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

type KnowledgeGraphHandler struct {
	usecase domain.KnowledgeGraphUsecase
	logger  *slog.Logger
}

func NewKnowledgeGraphHandler(uc domain.KnowledgeGraphUsecase, logger *slog.Logger) *KnowledgeGraphHandler {
	if logger == nil {
		logger = slog.Default()
	}
	return &KnowledgeGraphHandler{usecase: uc, logger: logger}
}

// AddWithSource proxies POST /knowledge_graph/add_with_source.
func (h *KnowledgeGraphHandler) AddWithSource(ctx context.Context, c *app.RequestContext) {
	var req dto.AddKnowledgeGraphWithSourceRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	nodes := make([]domain.KnowledgeGraphNode, 0, len(req.Nodes))
	for _, n := range req.Nodes {
		nodes = append(nodes, domain.KnowledgeGraphNode{
			ID:         n.ID,
			Name:       n.Name,
			Labels:     n.Labels,
			Properties: n.Properties,
		})
	}
	rels := make([]domain.KnowledgeGraphRelationship, 0, len(req.Relationships))
	for _, r := range req.Relationships {
		rels = append(rels, domain.KnowledgeGraphRelationship{
			Start:      r.Start,
			End:        r.End,
			Type:       r.Type,
			Properties: r.Properties,
		})
	}

	out, err := h.usecase.AddWithSource(ctx, &domain.AddKnowledgeGraphWithSourceRequest{
		Source:        req.Source,
		ClearExisting: req.ClearExisting,
		Nodes:         nodes,
		Relationships: rels,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, out)
}

// SearchWithSource proxies POST /knowledge_graph/search_with_source.
func (h *KnowledgeGraphHandler) SearchWithSource(ctx context.Context, c *app.RequestContext) {
	var req dto.SearchKnowledgeGraphWithSourceRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	out, err := h.usecase.SearchWithSource(ctx, &domain.SearchKnowledgeGraphWithSourceRequest{
		Source:               req.Source,
		NodeID:               req.NodeID,
		Label:                req.Label,
		PropertyName:         req.PropertyName,
		PropertyValue:        req.PropertyValue,
		RelationshipType:     req.RelationshipType,
		QueryText:            req.QueryText,
		TopK:                 req.TopK,
		IncludeRelationships: req.IncludeRelationships,
		RelationshipDepth:    req.RelationshipDepth,
		ReturnSVOOnly:        req.ReturnSVOOnly,
		Limit:                req.Limit,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, out)
}

// GetGraphBySource proxies POST /knowledge_graph/get_graph_by_source.
func (h *KnowledgeGraphHandler) GetGraphBySource(ctx context.Context, c *app.RequestContext) {
	var req dto.GetKnowledgeGraphBySourceRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	out, err := h.usecase.GetGraphBySource(ctx, &domain.GetKnowledgeGraphBySourceRequest{
		Source:    req.Source,
		NodeLimit: req.NodeLimit,
		RelLimit:  req.RelLimit,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, out)
}

// DeleteWithSource proxies DELETE /knowledge_graph/delete_with_source.
func (h *KnowledgeGraphHandler) DeleteWithSource(ctx context.Context, c *app.RequestContext) {
	var req dto.DeleteKnowledgeGraphWithSourceRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}
	out, err := h.usecase.DeleteWithSource(ctx, &domain.DeleteKnowledgeGraphWithSourceRequest{
		Source: req.Source,
	})
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, out)
}
