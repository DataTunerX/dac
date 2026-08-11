package handler

import (
	"context"
	"log/slog"
	"sort"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
	"github.com/lvyanru/dac-apiserver/internal/usecase"
)

// AgentContainerHandler handles agent container requests
type AgentContainerHandler struct {
	usecase usecase.AgentContainerUsecase
	logger  *slog.Logger
}

// NewAgentContainerHandler creates a new agent container handler
func NewAgentContainerHandler(uc usecase.AgentContainerUsecase, logger *slog.Logger) *AgentContainerHandler {
	return &AgentContainerHandler{
		usecase: uc,
		logger:  logger,
	}
}

// Create creates a new agent container
//
//	@Summary		Create Agent Container
//	@Description	Create a new AgentContainer resource in the specified namespace
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string							true	"Kubernetes namespace"
//	@Param			request		body		dto.CreateAgentContainerRequest		true	"AgentContainer configuration"
//	@Success		201			{object}	dto.AgentContainerResponse			"AgentContainer created"
//	@Failure		400			{object}	map[string]string				"Invalid request parameters"
//	@Failure		401			{object}	map[string]string				"Unauthorized"
//	@Router			/namespaces/{namespace}/agents [post]
func (h *AgentContainerHandler) Create(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")

	var req dto.CreateAgentContainerRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	skills := make([]entity.AgentSkill, 0, len(req.AgentCard.Skills))
	for _, s := range req.AgentCard.Skills {
		skills = append(skills, entity.AgentSkill{
			ID:          s.ID,
			Name:        s.Name,
			Description: s.Description,
			Tags:        s.Tags,
			Examples:    s.Examples,
		})
	}

	// Convert to domain request
	domainReq := &domain.CreateAgentContainerRequest{
		Name:                      req.Name,
		Namespace:                 namespace,
		Labels:                    req.Labels,
		DACType:                   req.DACType,
		DataPolicy: entity.DataPolicy{
			DataSourceType:     req.DataPolicy.DataSourceType,
			SemanticGroupID:    req.DataPolicy.SemanticGroupID,
			SourceNameSelector: req.DataPolicy.SourceNameSelector,
		},
		SkillPolicy: skillPolicyFromDTO(req.SkillPolicy),
		AgentCard: entity.AgentCard{
			Name:        req.AgentCard.Name,
			Description: req.AgentCard.Description,
			Skills:      skills,
		},
		Model: entity.ModelSpec{
			Embedding:  req.Model.Embedding,
			ExpertLLM:  req.Model.ExpertLLM,
			PlannerLLM: req.Model.PlannerLLM,
		},
		ExpertAgentMaxSteps:       req.ExpertAgentMaxSteps,
		OrchestratorAgentMaxLoops: req.OrchestratorAgentMaxLoops,
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
//	@Summary		Get Agent Container
//	@Description	Get details of an AgentContainer in the specified namespace
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string					true	"Kubernetes namespace"
//	@Param			name		path		string					true	"Agent name"
//	@Success		200			{object}	dto.AgentContainerResponse	"AgentContainer details"
//	@Failure		404			{object}	map[string]string		"AgentContainer not found"
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
//	@Summary		List Agent Containers across all namespaces
//	@Description	List AgentContainer resources across all namespaces in the cluster
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200			{object}	map[string]any	"AgentContainer list"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/agents [get]
func (h *AgentContainerHandler) ListAll(ctx context.Context, c *app.RequestContext) {
	lo := parseLimitOffset(c, 50, 200)
	opts := domain.ListOptions{
		AllNamespaces: true, // Explicit: list across all namespaces
		LabelSelector: c.Query("labelSelector"),
		FieldSelector: c.Query("fieldSelector"),
	}

	// Offset-based pagination: fetch full list then stable-sort and slice.
	opts.Limit = 0
	opts.Continue = ""

	// namespace parameter is ignored when AllNamespaces is true
	containers, err := h.usecase.List(ctx, "", opts)
	if err != nil {
		h.logger.Error("failed to list agent containers (all namespaces)",
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	sort.Slice(containers, func(i, j int) bool {
		if containers[i].Namespace != containers[j].Namespace {
			return containers[i].Namespace < containers[j].Namespace
		}
		return containers[i].Name < containers[j].Name
	})
	totalCount := len(containers)
	containers = paginateSlice(containers, lo.Offset, lo.Limit)

	items := make([]dto.AgentContainerResponse, len(containers))
	for i, container := range containers {
		items[i] = dto.ToAgentContainerResponse(container)
	}
	SuccessResponse(c, map[string]any{
		"items":      items,
		"totalCount": totalCount,
		"limit":      lo.Limit,
		"offset":     lo.Offset,
	})
}

// List lists agent containers
//
//	@Summary		List Agent Containers
//	@Description	List AgentContainer resources in the specified namespace
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string	true	"Kubernetes namespace"
//	@Success		200			{object}	map[string]any	"AgentContainer list"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/namespaces/{namespace}/agents [get]
func (h *AgentContainerHandler) List(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	lo := parseLimitOffset(c, 50, 200)

	opts := domain.ListOptions{
		AllNamespaces: false, // Explicit: list single namespace
		LabelSelector: c.Query("labelSelector"),
		FieldSelector: c.Query("fieldSelector"),
	}

	opts.Limit = 0
	opts.Continue = ""

	containers, err := h.usecase.List(ctx, namespace, opts)
	if err != nil {
		h.logger.Error("failed to list agent containers",
			"namespace", namespace,
			"error", err,
		)
		ErrorResponse(c, err)
		return
	}

	sort.Slice(containers, func(i, j int) bool {
		return containers[i].Name < containers[j].Name
	})
	totalCount := len(containers)
	containers = paginateSlice(containers, lo.Offset, lo.Limit)

	items := make([]dto.AgentContainerResponse, len(containers))
	for i, container := range containers {
		items[i] = dto.ToAgentContainerResponse(container)
	}

	SuccessResponse(c, map[string]any{
		"items":      items,
		"totalCount": totalCount,
		"limit":      lo.Limit,
		"offset":     lo.Offset,
	})
}

// Update updates an agent container
//
//	@Summary		Update Agent Container
//	@Description	Update the configuration of an AgentContainer in the specified namespace
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string							true	"Kubernetes namespace"
//	@Param			name		path		string							true	"Agent name"
//	@Param			request		body		dto.UpdateAgentContainerRequest		true	"Update payload"
//	@Success		200			{object}	dto.AgentContainerResponse			"Updated successfully"
//	@Failure		400			{object}	map[string]string				"Invalid request parameters"
//	@Failure		404			{object}	map[string]string				"AgentContainer not found"
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
	var dataPolicy *entity.DataPolicy
	if req.DataPolicy != nil {
		dataPolicy = &entity.DataPolicy{
			DataSourceType:     req.DataPolicy.DataSourceType,
			SemanticGroupID:    req.DataPolicy.SemanticGroupID,
			SourceNameSelector: req.DataPolicy.SourceNameSelector,
		}
	}

	var skillPolicy *entity.SkillPolicy
	if req.SkillPolicy != nil {
		sp := skillPolicyFromDTO(*req.SkillPolicy)
		skillPolicy = &sp
	}

	var agentCard *entity.AgentCard
	if req.AgentCard != nil {
		skills := make([]entity.AgentSkill, 0, len(req.AgentCard.Skills))
		for _, s := range req.AgentCard.Skills {
			skills = append(skills, entity.AgentSkill{
				ID:          s.ID,
				Name:        s.Name,
				Description: s.Description,
				Tags:        s.Tags,
				Examples:    s.Examples,
			})
		}
		agentCard = &entity.AgentCard{
			Name:        req.AgentCard.Name,
			Description: req.AgentCard.Description,
			Skills:      skills,
		}
	}

	var model *entity.ModelSpec
	if req.Model != nil {
		model = &entity.ModelSpec{
			Embedding:  req.Model.Embedding,
			ExpertLLM:  req.Model.ExpertLLM,
			PlannerLLM: req.Model.PlannerLLM,
		}
	}

	domainReq := &domain.UpdateAgentContainerRequest{
		Labels:                    req.Labels,
		DACType:                   req.DACType,
		DataPolicy:                dataPolicy,
		SkillPolicy:               skillPolicy,
		AgentCard:                 agentCard,
		Model:                     model,
		ExpertAgentMaxSteps:       req.ExpertAgentMaxSteps,
		OrchestratorAgentMaxLoops: req.OrchestratorAgentMaxLoops,
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
//	@Summary		Delete Agent Container
//	@Description	Delete an AgentContainer from the specified namespace
//	@Tags			Agent Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			namespace	path		string				true	"Kubernetes namespace"
//	@Param			name		path		string				true	"Agent name"
//	@Success		200			{object}	map[string]string	"Deleted successfully"
//	@Failure		404			{object}	map[string]string	"AgentContainer not found"
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

// skillPolicyFromDTO maps API skillPolicy into the domain entity.
func skillPolicyFromDTO(p dto.SkillPolicyDTO) entity.SkillPolicy {
	skills := make([]entity.SkillRef, 0, len(p.Skills))
	for _, s := range p.Skills {
		skills = append(skills, entity.SkillRef{
			Namespace: s.Namespace,
			Name:      s.Name,
			Version:   s.Version,
		})
	}
	return entity.SkillPolicy{Skills: skills}
}
