package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

type AgentRegistryHandler struct {
	usecase domain.AgentRegistryUsecase
	logger  *slog.Logger
}

func NewAgentRegistryHandler(uc domain.AgentRegistryUsecase, logger *slog.Logger) *AgentRegistryHandler {
	return &AgentRegistryHandler{usecase: uc, logger: logger}
}

// ListRegistries lists configured agent registries and their reachability.
//
//	@Summary		List agent registries
//	@Description	List orchestrator-registry and biz-orchestrator-registry status
//	@Tags			Observability
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200	{object}	map[string]any
//	@Router			/observability/agent-registries [get]
func (h *AgentRegistryHandler) ListRegistries(ctx context.Context, c *app.RequestContext) {
	items, err := h.usecase.ListRegistries(ctx)
	if err != nil {
		h.logger.Error("failed to list agent registries", "error", err)
		ErrorResponse(c, err)
		return
	}

	resp := make([]dto.AgentRegistrySummaryResponse, 0, len(items))
	for _, item := range items {
		resp = append(resp, dto.ToAgentRegistrySummaryResponse(item))
	}
	SuccessResponse(c, map[string]any{"items": resp, "totalCount": len(resp)})
}

// ListAgents lists registered agent cards for one registry.
//
//	@Summary		List registered agents
//	@Description	List A2A agent cards from orchestrator-registry or biz-orchestrator-registry
//	@Tags			Observability
//	@Produce		json
//	@Security		BearerAuth
//	@Param			registry	path		string	true	"orchestrator-registry|biz-orchestrator-registry"
//	@Success		200			{object}	map[string]any
//	@Router			/observability/agent-registries/{registry}/agents [get]
func (h *AgentRegistryHandler) ListAgents(ctx context.Context, c *app.RequestContext) {
	registry := c.Param("registry")
	if _, ok := domain.ValidAgentRegistryNames[registry]; !ok {
		ErrorResponse(c, domain.NewInvalidInputError("registry must be orchestrator-registry or biz-orchestrator-registry"))
		return
	}

	items, err := h.usecase.ListAgents(ctx, registry)
	if err != nil {
		h.logger.Error("failed to list registered agents", "error", err, "registry", registry)
		ErrorResponse(c, err)
		return
	}

	resp := make([]dto.RegisteredAgentCardResponse, 0, len(items))
	for _, item := range items {
		resp = append(resp, dto.ToRegisteredAgentCardResponse(item))
	}
	SuccessResponse(c, map[string]any{"items": resp, "totalCount": len(resp), "registry": registry})
}
