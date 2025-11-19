package handler

import (
	"context"
	"log/slog"
	"strconv"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
	"github.com/lvyanru/dac-apiserver/internal/usecase"
)

// AgentContainerHandler handles agent container requests
type AgentContainerHandler struct {
	usecase usecase.AgentContainerUsecase
	logger  *slog.Logger
}

// NewAgentContainerHandler creates a new agent container handler
func NewAgentContainerHandler(uc usecase.AgentContainerUsecase) *AgentContainerHandler {
	return &AgentContainerHandler{
		usecase: uc,
		logger:  slog.Default(),
	}
}

// Create creates a new agent container
//
//	@Summary		Create Agent
//	@Description	Create new Agent container resource in specified namespace
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string							true	"Kubernetes namespace"
//	@Param			request		body		dto.CreateAgentContainerRequest		true	"Agent configuration"
//	@Success		200			{object}	dto.AgentContainerResponse			"Created successfully"
//	@Failure		400			{object}	map[string]string				"Invalid request parameters"
//	@Failure		401			{object}	map[string]string				"Unauthorized"
//	@Router			/namespaces/{namespace}/agents [post]
func (h *AgentContainerHandler) Create(ctx context.Context, c *app.RequestContext) {
	var req dto.CreateAgentContainerRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// Convert to domain request
	domainReq := &domain.CreateAgentContainerRequest{
		Name:                req.Name,
		Namespace:           req.Namespace,
		Labels:              req.Labels,
		DataPolicy:          req.DataPolicy,
		AgentCard:           req.AgentCard,
		Model:               req.Model,
		ExpertAgentMaxSteps: req.ExpertAgentMaxSteps,
	}

	container, err := h.usecase.Create(ctx, domainReq)
	if err != nil {
		h.logger.Error("failed to create agent container", "error", err)
		ErrorResponse(c, err)
		return
	}

	CreatedResponse(c, dto.ToAgentContainerResponse(container))
}

// Get retrieves an agent container
//
//	@Summary		Get Agent details
//	@Description	based on名称Get detailed information of specified Agent
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string					true	"Kubernetes namespace"
//	@Param			name		path		string					true	"Agent 名称"
//	@Success		200			{object}	dto.AgentContainerResponse	"Agent 详情"
//	@Failure		404			{object}	map[string]string		"Agent not found"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/namespaces/{namespace}/agents/{name} [get]
func (h *AgentContainerHandler) Get(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	container, err := h.usecase.Get(ctx, namespace, name)
	if err != nil {
		h.logger.Error("failed to get agent container",
			"namespace", namespace,
			"name", name,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, dto.ToAgentContainerResponse(container))
}

// ListAll lists agent containers across all namespaces
//
//	@Summary		所有命名空间of Agent list
//	@Description	get所有命名空间下of Agent
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200			{object}	map[string]interface{}	"Agent list"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/agents [get]
func (h *AgentContainerHandler) ListAll(ctx context.Context, c *app.RequestContext) {
	opts := domain.ListOptions{
		AllNamespaces: true, // Explicit: list across all namespaces
		LabelSelector: c.Query("labelSelector"),
		FieldSelector: c.Query("fieldSelector"),
	}

	if limit := c.Query("limit"); limit != "" {
		if l, err := strconv.ParseInt(limit, 10, 64); err == nil {
			opts.Limit = l
		}
	}

	opts.Continue = c.Query("continue")

	// namespace parameter is ignored when AllNamespaces is true
	containers, err := h.usecase.List(ctx, "", opts)
	if err != nil {
		h.logger.Error("failed to list agent containers (all namespaces)",
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	// Convert to response DTOs
	items := make([]dto.AgentContainerResponse, len(containers))
	for i, container := range containers {
		items[i] = dto.ToAgentContainerResponse(container)
	}

	SuccessResponse(c, map[string]interface{}{
		"items": items,
		"total": len(items),
	})
}

// List lists agent containers
//
//	@Summary		Agent list
//	@Description	get指定命名空间下of所有 Agent
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string	true	"Kubernetes namespace"
//	@Success		200			{object}	map[string]interface{}	"Agent list"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/namespaces/{namespace}/agents [get]
func (h *AgentContainerHandler) List(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")

	opts := domain.ListOptions{
		AllNamespaces: false, // Explicit: list single namespace
		LabelSelector: c.Query("labelSelector"),
		FieldSelector: c.Query("fieldSelector"),
	}

	if limit := c.Query("limit"); limit != "" {
		if l, err := strconv.ParseInt(limit, 10, 64); err == nil {
			opts.Limit = l
		}
	}

	opts.Continue = c.Query("continue")

	containers, err := h.usecase.List(ctx, namespace, opts)
	if err != nil {
		h.logger.Error("failed to list agent containers",
			"namespace", namespace,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	// Convert to response DTOs
	items := make([]dto.AgentContainerResponse, len(containers))
	for i, container := range containers {
		items[i] = dto.ToAgentContainerResponse(container)
	}

	SuccessResponse(c, map[string]interface{}{
		"items": items,
		"total": len(items),
	})
}

// Update updates an agent container
//
//	@Summary		Update Agent
//	@Description	更new指定 Agent of配置
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string							true	"Kubernetes namespace"
//	@Param			name		path		string							true	"Agent 名称"
//	@Param			request		body		dto.UpdateAgentContainerRequest		true	"更new内容"
//	@Success		200			{object}	dto.AgentContainerResponse			"Updated successfully"
//	@Failure		400			{object}	map[string]string				"Invalid request parameters"
//	@Failure		404			{object}	map[string]string				"Agent not found"
//	@Failure		401			{object}	map[string]string				"Unauthorized"
//	@Router			/namespaces/{namespace}/agents/{name} [put]
func (h *AgentContainerHandler) Update(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	var req dto.UpdateAgentContainerRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// Convert to domain request
	domainReq := &domain.UpdateAgentContainerRequest{
		Labels:              req.Labels,
		DataPolicy:          req.DataPolicy,
		AgentCard:           req.AgentCard,
		Model:               req.Model,
		ExpertAgentMaxSteps: req.ExpertAgentMaxSteps,
	}

	container, err := h.usecase.Update(ctx, namespace, name, domainReq)
	if err != nil {
		h.logger.Error("failed to update agent container",
			"namespace", namespace,
			"name", name,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, dto.ToAgentContainerResponse(container))
}

// Delete deletes an agent container
//
//	@Summary		Delete Agent
//	@Description	删除指定of Agent 资源
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string				true	"Kubernetes namespace"
//	@Param			name		path		string				true	"Agent 名称"
//	@Success		200			{object}	map[string]string	"Deleted successfully"
//	@Failure		404			{object}	map[string]string	"Agent not found"
//	@Failure		401			{object}	map[string]string	"Unauthorized"
//	@Router			/namespaces/{namespace}/agents/{name} [delete]
func (h *AgentContainerHandler) Delete(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if err := h.usecase.Delete(ctx, namespace, name); err != nil {
		h.logger.Error("failed to delete agent container",
			"namespace", namespace,
			"name", name,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, map[string]string{
		"message": "agent container deleted successfully",
	})
}
