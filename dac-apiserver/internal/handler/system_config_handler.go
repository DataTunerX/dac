package handler

import (
	"context"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// SystemConfigHandler manages cluster-wide dac-configuration / dd-configuration ConfigMaps.
type SystemConfigHandler struct {
	usecase domain.SystemConfigUsecase
	logger  *slog.Logger
}

func NewSystemConfigHandler(uc domain.SystemConfigUsecase, logger *slog.Logger) *SystemConfigHandler {
	return &SystemConfigHandler{usecase: uc, logger: logger}
}

// List lists active system configurations (dac-configuration and dd-configuration).
//
//	@Summary		List system configurations
//	@Description	List active dac-configuration and dd-configuration (images and LLM fields only)
//	@Tags			System Configuration
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200	{object}	map[string]any
//	@Router			/system/configurations [get]
func (h *SystemConfigHandler) List(ctx context.Context, c *app.RequestContext) {
	items, err := h.usecase.List(ctx)
	if err != nil {
		h.logger.Error("failed to list system configurations", "error", err)
		ErrorResponse(c, err)
		return
	}

	resp := make([]dto.SystemConfigurationResponse, 0, len(items))
	for _, item := range items {
		resp = append(resp, dto.ToSystemConfigurationResponse(item))
	}
	SuccessResponse(c, map[string]any{"items": resp, "totalCount": len(resp)})
}

// Get returns the active system configuration by name.
//
//	@Summary		Get system configuration
//	@Description	Get active dac-configuration or dd-configuration (images and LLM fields only)
//	@Tags			System Configuration
//	@Produce		json
//	@Security		BearerAuth
//	@Param			name	path		string	true	"dac-configuration|dd-configuration"
//	@Success		200		{object}	dto.SystemConfigurationResponse
//	@Router			/system/configurations/{name} [get]
func (h *SystemConfigHandler) Get(ctx context.Context, c *app.RequestContext) {
	name, err := parseSystemConfigName(c.Param("name"))
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	cfg, err := h.usecase.Get(ctx, name)
	if err != nil {
		h.logger.Error("failed to get system configuration", "error", err, "name", name)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSystemConfigurationResponse(cfg))
}

// ListVersions lists archived versions for a system configuration.
//
//	@Summary		List system configuration versions
//	@Description	List archived versions created on each update
//	@Tags			System Configuration
//	@Produce		json
//	@Security		BearerAuth
//	@Param			name	path		string	true	"dac-configuration|dd-configuration"
//	@Success		200		{object}	map[string]any
//	@Router			/system/configurations/{name}/versions [get]
func (h *SystemConfigHandler) ListVersions(ctx context.Context, c *app.RequestContext) {
	name, err := parseSystemConfigName(c.Param("name"))
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	items, err := h.usecase.ListVersions(ctx, name)
	if err != nil {
		h.logger.Error("failed to list system configuration versions", "error", err, "name", name)
		ErrorResponse(c, err)
		return
	}

	lo := parseLimitOffset(c, 20, 100)
	totalCount := len(items)
	itemsPage := paginateSlice(items, lo.Offset, lo.Limit)

	resp := make([]dto.SystemConfigurationVersionResponse, 0, len(itemsPage))
	for _, item := range itemsPage {
		resp = append(resp, dto.ToSystemConfigurationVersionResponse(item))
	}

	SuccessResponse(c, map[string]any{
		"items":      resp,
		"totalCount": totalCount,
		"limit":      lo.Limit,
		"offset":     lo.Offset,
	})
}

// GetVersion returns a specific archived version.
//
//	@Summary		Get system configuration version
//	@Description	Get an archived dac-configuration or dd-configuration version
//	@Tags			System Configuration
//	@Produce		json
//	@Security		BearerAuth
//	@Param			name	path		string	true	"dac-configuration|dd-configuration"
//	@Param			version	path		string	true	"version id (UTC timestamp)"
//	@Success		200		{object}	dto.SystemConfigurationVersionResponse
//	@Router			/system/configurations/{name}/versions/{version} [get]
func (h *SystemConfigHandler) GetVersion(ctx context.Context, c *app.RequestContext) {
	name, err := parseSystemConfigName(c.Param("name"))
	if err != nil {
		ErrorResponse(c, err)
		return
	}
	version := c.Param("version")

	item, err := h.usecase.GetVersion(ctx, name, version)
	if err != nil {
		h.logger.Error("failed to get system configuration version", "error", err, "name", name, "version", version)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSystemConfigurationVersionResponse(item))
}

// Update updates the active configuration and archives the previous snapshot.
//
//	@Summary		Update system configuration
//	@Description	Update dac-configuration or dd-configuration; requires resourceVersion from GET for optimistic locking; archives the previous ConfigMap with a version suffix
//	@Tags			System Configuration
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			name	path		string	true	"dac-configuration|dd-configuration"
//	@Param			request	body		dto.UpdateSystemConfigurationRequest	true	"exposed fields"
//	@Success		200		{object}	dto.SystemConfigurationResponse
//	@Router			/system/configurations/{name} [put]
func (h *SystemConfigHandler) Update(ctx context.Context, c *app.RequestContext) {
	name, err := parseSystemConfigName(c.Param("name"))
	if err != nil {
		ErrorResponse(c, err)
		return
	}

	var req dto.UpdateSystemConfigurationRequest
	if err := c.BindAndValidate(&req); err != nil {
		h.logger.Error("invalid system configuration update request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	updated, err := h.usecase.Update(ctx, name, &domain.UpdateSystemConfigurationRequest{
		Data:            req.Data,
		ResourceVersion: req.ResourceVersion,
	})
	if err != nil {
		h.logger.Error("failed to update system configuration", "error", err, "name", name)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSystemConfigurationResponse(updated))
}

func parseSystemConfigName(raw string) (domain.SystemConfigName, error) {
	name := domain.SystemConfigName(raw)
	if !name.IsValid() {
		return "", domain.NewInvalidInputError("name must be dac-configuration or dd-configuration")
	}
	return name, nil
}
