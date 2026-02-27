package usecase

import (
	"context"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/dataservices"
)

type knowledgeGraphUsecase struct {
	dsClient *dataservices.Client
	logger   *slog.Logger
}

func NewKnowledgeGraphUsecase(dsClient *dataservices.Client, logger *slog.Logger) domain.KnowledgeGraphUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &knowledgeGraphUsecase{dsClient: dsClient, logger: logger}
}

func (u *knowledgeGraphUsecase) AddWithSource(ctx context.Context, req *domain.AddKnowledgeGraphWithSourceRequest) (map[string]any, error) {
	if req == nil || req.Source == "" {
		return nil, domain.NewInvalidInputError("source is required")
	}

	nodes := make([]map[string]any, 0, len(req.Nodes))
	for _, n := range req.Nodes {
		m := map[string]any{
			"id": n.ID,
		}
		if n.Name != "" {
			m["name"] = n.Name
		}
		if len(n.Labels) > 0 {
			m["labels"] = n.Labels
		}
		if n.Properties != nil {
			m["properties"] = n.Properties
		}
		nodes = append(nodes, m)
	}

	rels := make([]map[string]any, 0, len(req.Relationships))
	for _, r := range req.Relationships {
		m := map[string]any{
			"start": r.Start,
			"end":   r.End,
			"type":  r.Type,
		}
		if r.Properties != nil {
			m["properties"] = r.Properties
		}
		rels = append(rels, m)
	}

	dsReq := map[string]any{
		"source":         req.Source,
		"clear_existing": req.ClearExisting,
		"nodes":          nodes,
		"relationships":  rels,
	}
	return u.dsClient.KnowledgeGraphAddWithSource(ctx, dsReq)
}

func (u *knowledgeGraphUsecase) SearchWithSource(ctx context.Context, req *domain.SearchKnowledgeGraphWithSourceRequest) (map[string]any, error) {
	if req == nil || req.Source == "" {
		return nil, domain.NewInvalidInputError("source is required")
	}
	dsReq := map[string]any{
		"source": req.Source,
	}
	if req.NodeID != "" {
		dsReq["node_id"] = req.NodeID
	}
	if req.Label != "" {
		dsReq["label"] = req.Label
	}
	if req.PropertyName != "" {
		dsReq["property_name"] = req.PropertyName
	}
	if req.PropertyValue != "" {
		dsReq["property_value"] = req.PropertyValue
	}
	if req.RelationshipType != "" {
		dsReq["relationship_type"] = req.RelationshipType
	}
	if req.QueryText != "" {
		dsReq["query_text"] = req.QueryText
	}
	if req.TopK > 0 {
		dsReq["top_k"] = req.TopK
	}
	// keep explicit bools even if false? data-services uses defaults; but allowing user to set.
	dsReq["include_relationships"] = req.IncludeRelationships
	if req.RelationshipDepth != 0 {
		dsReq["relationship_depth"] = req.RelationshipDepth
	}
	dsReq["return_svo_only"] = req.ReturnSVOOnly
	if req.Limit > 0 {
		dsReq["limit"] = req.Limit
	}

	return u.dsClient.KnowledgeGraphSearchWithSource(ctx, dsReq)
}

func (u *knowledgeGraphUsecase) GetGraphBySource(ctx context.Context, req *domain.GetKnowledgeGraphBySourceRequest) (map[string]any, error) {
	if req == nil || req.Source == "" {
		return nil, domain.NewInvalidInputError("source is required")
	}
	dsReq := map[string]any{
		"source": req.Source,
	}
	if req.NodeLimit > 0 {
		dsReq["node_limit"] = req.NodeLimit
	}
	if req.RelLimit > 0 {
		dsReq["rel_limit"] = req.RelLimit
	}
	return u.dsClient.KnowledgeGraphGetGraphBySource(ctx, dsReq)
}

func (u *knowledgeGraphUsecase) DeleteWithSource(ctx context.Context, req *domain.DeleteKnowledgeGraphWithSourceRequest) (map[string]any, error) {
	if req == nil || req.Source == "" {
		return nil, domain.NewInvalidInputError("source is required")
	}
	dsReq := map[string]any{"source": req.Source}
	return u.dsClient.KnowledgeGraphDeleteWithSource(ctx, dsReq)
}
