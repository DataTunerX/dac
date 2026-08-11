package handler

import (
	"context"
	"fmt"
	"log/slog"
	"path/filepath"
	"strings"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

type SkillHubHandler struct {
	usecase domain.SkillHubUsecase
	logger  *slog.Logger
}

func NewSkillHubHandler(uc domain.SkillHubUsecase, logger *slog.Logger) *SkillHubHandler {
	return &SkillHubHandler{usecase: uc, logger: logger}
}

// ListNamespaces lists skill-hub namespaces.
//
//	@Summary		List skill namespaces
//	@Tags			Skills
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200	{object}	map[string]any
//	@Router			/skills/namespaces [get]
func (h *SkillHubHandler) ListNamespaces(ctx context.Context, c *app.RequestContext) {
	items, err := h.usecase.ListNamespaces(ctx)
	if err != nil {
		h.logger.Error("failed to list skill namespaces", "error", err)
		ErrorResponse(c, err)
		return
	}
	resp := make([]dto.SkillNamespaceResponse, 0, len(items))
	for _, item := range items {
		resp = append(resp, dto.ToSkillNamespaceResponse(item))
	}
	SuccessResponse(c, map[string]any{"items": resp, "totalCount": len(resp)})
}

// CreateNamespace creates a skill-hub namespace.
//
//	@Summary		Create skill namespace
//	@Tags			Skills
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			body	body		dto.CreateSkillNamespaceRequest	true	"namespace"
//	@Success		201		{object}	map[string]any
//	@Router			/skills/namespaces [post]
func (h *SkillHubHandler) CreateNamespace(ctx context.Context, c *app.RequestContext) {
	var req dto.CreateSkillNamespaceRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.NewInvalidInputError(err.Error()))
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		ErrorResponse(c, domain.NewInvalidInputError("name is required"))
		return
	}
	item, err := h.usecase.CreateNamespace(ctx, req.Name)
	if err != nil {
		h.logger.Error("failed to create skill namespace", "error", err, "namespace", req.Name)
		ErrorResponse(c, err)
		return
	}
	CreatedResponse(c, dto.ToSkillNamespaceResponse(*item))
}

// NamespaceExists checks whether a skill-hub namespace exists.
//
//	@Summary		Check skill namespace exists
//	@Tags			Skills
//	@Produce		json
//	@Security		BearerAuth
//	@Param			ns	path		string	true	"namespace"
//	@Success		200	{object}	map[string]any
//	@Router			/skills/namespaces/{ns}/exists [get]
func (h *SkillHubHandler) NamespaceExists(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	exists, err := h.usecase.NamespaceExists(ctx, ns)
	if err != nil {
		h.logger.Error("failed to check skill namespace", "error", err, "namespace", ns)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, map[string]any{"namespace": ns, "exists": exists})
}

// DeleteNamespace deletes an empty skill-hub namespace.
//
//	@Summary		Delete skill namespace
//	@Tags			Skills
//	@Security		BearerAuth
//	@Param			ns	path	string	true	"namespace"
//	@Success		204
//	@Router			/skills/namespaces/{ns} [delete]
func (h *SkillHubHandler) DeleteNamespace(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	if err := h.usecase.DeleteNamespace(ctx, ns); err != nil {
		h.logger.Error("failed to delete skill namespace", "error", err, "namespace", ns)
		ErrorResponse(c, err)
		return
	}
	NoContentResponse(c)
}

// ListSkills lists skills in a namespace.
//
//	@Summary		List skills
//	@Tags			Skills
//	@Produce		json
//	@Security		BearerAuth
//	@Param			ns	path		string	true	"namespace"
//	@Success		200	{object}	map[string]any
//	@Router			/skills/namespaces/{ns}/skills [get]
func (h *SkillHubHandler) ListSkills(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	items, err := h.usecase.ListSkills(ctx, ns)
	if err != nil {
		h.logger.Error("failed to list skills", "error", err, "namespace", ns)
		ErrorResponse(c, err)
		return
	}
	resp := make([]dto.SkillInfoResponse, 0, len(items))
	for _, item := range items {
		resp = append(resp, dto.ToSkillInfoResponse(item))
	}
	SuccessResponse(c, map[string]any{"items": resp, "totalCount": len(resp), "namespace": ns})
}

// GetSkill returns full skill pack metadata (detail / allowed_tools / …).
//
//	@Summary		Get skill detail
//	@Tags			Skills
//	@Produce		json
//	@Security		BearerAuth
//	@Param			ns		path		string	true	"namespace"
//	@Param			name	path		string	true	"skill name"
//	@Param			version	query		string	false	"version"
//	@Success		200		{object}	map[string]any
//	@Router			/skills/namespaces/{ns}/skills/{name} [get]
func (h *SkillHubHandler) GetSkill(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	name := c.Param("name")
	version := string(c.Query("version"))
	item, err := h.usecase.GetSkill(ctx, ns, name, version)
	if err != nil {
		h.logger.Error("failed to get skill detail", "error", err, "namespace", ns, "name", name)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSkillDetailResponse(*item))
}

// CreateSkill creates a skill from structured fields (skill-hub packs the zip).
//
//	@Summary		Create skill
//	@Tags			Skills
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			ns		path		string					true	"namespace"
//	@Param			body	body		dto.CreateSkillRequest	true	"skill fields"
//	@Success		201		{object}	map[string]any
//	@Router			/skills/namespaces/{ns}/skills/create [post]
func (h *SkillHubHandler) CreateSkill(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	var req dto.CreateSkillRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.NewInvalidInputError(err.Error()))
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		ErrorResponse(c, domain.NewInvalidInputError("name is required"))
		return
	}
	if strings.TrimSpace(req.Description) == "" {
		ErrorResponse(c, domain.NewInvalidInputError("description is required"))
		return
	}
	tools := req.AllowedTools
	if tools == nil {
		tools = []string{}
	}
	item, err := h.usecase.CreateSkill(ctx, ns, domain.CreateSkillRequest{
		Name:         req.Name,
		Description:  req.Description,
		Detail:       req.Detail,
		Version:      req.Version,
		AllowedTools: tools,
	})
	if err != nil {
		h.logger.Error("failed to create skill", "error", err, "namespace", ns, "name", req.Name)
		ErrorResponse(c, err)
		return
	}
	CreatedResponse(c, dto.ToSkillInfoResponse(*item))
}

// UpdateSkill updates skill pack metadata while preserving scripts / resources.
//
//	@Summary		Update skill
//	@Tags			Skills
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			ns		path		string					true	"namespace"
//	@Param			name	path		string					true	"skill name"
//	@Param			version	query		string					false	"source version to edit"
//	@Param			body	body		dto.CreateSkillRequest	true	"skill fields"
//	@Success		200		{object}	map[string]any
//	@Router			/skills/namespaces/{ns}/skills/{name}/update [post]
func (h *SkillHubHandler) UpdateSkill(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	name := c.Param("name")
	sourceVersion := string(c.Query("version"))
	var req dto.CreateSkillRequest
	if err := c.BindAndValidate(&req); err != nil {
		ErrorResponse(c, domain.NewInvalidInputError(err.Error()))
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		req.Name = name
	}
	if strings.TrimSpace(req.Name) != strings.TrimSpace(name) {
		ErrorResponse(c, domain.NewInvalidInputError("name in body must match path name"))
		return
	}
	if strings.TrimSpace(req.Description) == "" {
		ErrorResponse(c, domain.NewInvalidInputError("description is required"))
		return
	}
	tools := req.AllowedTools
	if tools == nil {
		tools = []string{}
	}
	item, err := h.usecase.UpdateSkill(ctx, ns, name, sourceVersion, domain.CreateSkillRequest{
		Name:         req.Name,
		Description:  req.Description,
		Detail:       req.Detail,
		Version:      req.Version,
		AllowedTools: tools,
	})
	if err != nil {
		h.logger.Error("failed to update skill", "error", err, "namespace", ns, "name", name)
		ErrorResponse(c, err)
		return
	}
	SuccessResponse(c, dto.ToSkillInfoResponse(*item))
}

// UploadSkill uploads a skill zip to a namespace.
//
//	@Summary		Upload skill
//	@Tags			Skills
//	@Accept			mpfd
//	@Produce		json
//	@Security		BearerAuth
//	@Param			ns		path		string	true	"namespace"
//	@Param			file	formData	file	true	"skill zip"
//	@Success		201		{object}	map[string]any
//	@Router			/skills/namespaces/{ns}/skills [post]
func (h *SkillHubHandler) UploadSkill(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	fileHeader, err := c.FormFile("file")
	if err != nil {
		ErrorResponse(c, domain.NewInvalidInputError("multipart field 'file' is required"))
		return
	}
	f, err := fileHeader.Open()
	if err != nil {
		ErrorResponse(c, domain.NewInternalError(err))
		return
	}
	defer f.Close()

	filename := filepath.Base(fileHeader.Filename)
	if filename == "" || filename == "." || filename == "/" {
		filename = "skill.zip"
	}
	if !strings.HasSuffix(strings.ToLower(filename), ".zip") {
		ErrorResponse(c, domain.NewInvalidInputError("file must be a .zip package"))
		return
	}

	item, err := h.usecase.UploadSkill(ctx, ns, filename, f)
	if err != nil {
		h.logger.Error("failed to upload skill", "error", err, "namespace", ns, "filename", filename)
		ErrorResponse(c, err)
		return
	}
	CreatedResponse(c, dto.ToSkillInfoResponse(*item))
}

// DownloadSkill downloads a skill zip.
//
//	@Summary		Download skill
//	@Tags			Skills
//	@Produce		application/zip
//	@Security		BearerAuth
//	@Param			ns		path	string	true	"namespace"
//	@Param			name	path	string	true	"skill name"
//	@Param			version	query	string	false	"version"
//	@Success		200
//	@Router			/skills/namespaces/{ns}/skills/{name}/download [get]
func (h *SkillHubHandler) DownloadSkill(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	name := c.Param("name")
	version := string(c.Query("version"))

	dl, err := h.usecase.DownloadSkill(ctx, ns, name, version)
	if err != nil {
		h.logger.Error("failed to download skill", "error", err, "namespace", ns, "name", name)
		ErrorResponse(c, err)
		return
	}

	c.Response.Header.Set("Content-Type", "application/zip")
	c.Response.Header.Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, dl.Filename))
	if dl.Version != "" {
		c.Response.Header.Set("X-Skill-Version", dl.Version)
	}
	size := -1
	if dl.Size > 0 {
		size = int(dl.Size)
	}
	c.SetBodyStream(dl.Body, size)
}

// DeleteSkill deletes a skill version (latest if version omitted).
//
//	@Summary		Delete skill
//	@Tags			Skills
//	@Security		BearerAuth
//	@Param			ns		path	string	true	"namespace"
//	@Param			name	path	string	true	"skill name"
//	@Param			version	query	string	false	"version"
//	@Success		204
//	@Router			/skills/namespaces/{ns}/skills/{name} [delete]
func (h *SkillHubHandler) DeleteSkill(ctx context.Context, c *app.RequestContext) {
	ns := c.Param("ns")
	name := c.Param("name")
	version := string(c.Query("version"))
	if err := h.usecase.DeleteSkill(ctx, ns, name, version); err != nil {
		h.logger.Error("failed to delete skill", "error", err, "namespace", ns, "name", name)
		ErrorResponse(c, err)
		return
	}
	NoContentResponse(c)
}

// Reload rebuilds the skill-hub index.
//
//	@Summary		Reload skill index
//	@Tags			Skills
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200	{object}	map[string]any
//	@Router			/skills/reload [post]
func (h *SkillHubHandler) Reload(ctx context.Context, c *app.RequestContext) {
	items, err := h.usecase.Reload(ctx)
	if err != nil {
		h.logger.Error("failed to reload skills", "error", err)
		ErrorResponse(c, err)
		return
	}
	resp := make([]dto.SkillInfoResponse, 0, len(items))
	for _, item := range items {
		resp = append(resp, dto.ToSkillInfoResponse(item))
	}
	SuccessResponse(c, map[string]any{"items": resp, "totalCount": len(resp)})
}
