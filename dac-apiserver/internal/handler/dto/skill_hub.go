package dto

import "github.com/lvyanru/dac-apiserver/internal/domain"

type SkillInfoResponse struct {
	Name              string   `json:"name"`
	Namespace         string   `json:"namespace"`
	Description       string   `json:"description"`
	Version           string   `json:"version"`
	Filename          string   `json:"filename"`
	AvailableVersions []string `json:"availableVersions"`
}

type SkillScriptInfoResponse struct {
	ScriptName  string `json:"scriptName"`
	Interpreter string `json:"interpreter"`
}

// SkillDetailResponse is the BFF view of a skill pack (camelCase for the UI).
type SkillDetailResponse struct {
	Name              string                    `json:"name"`
	Namespace         string                    `json:"namespace"`
	Description       string                    `json:"description"`
	Detail            string                    `json:"detail"` // SKILL.md body
	Version           string                    `json:"version"`
	Filename          string                    `json:"filename"`
	AvailableVersions []string                  `json:"availableVersions"`
	AllowedTools      []string                  `json:"allowedTools"` // empty = unrestricted
	Scripts           []SkillScriptInfoResponse `json:"scripts"`
	ResourceDirs      []string                  `json:"resourceDirs"`
}

type SkillNamespaceResponse struct {
	ID         string `json:"id"`
	Visibility string `json:"visibility"`
}

type CreateSkillNamespaceRequest struct {
	Name string `json:"name" binding:"required"`
}

// CreateSkillRequest creates a skill from form fields (skill-hub packs the zip).
// slug is not exposed; skill-hub always writes _meta.json slug = name.
type CreateSkillRequest struct {
	Name         string   `json:"name" binding:"required"`
	Description  string   `json:"description" binding:"required"`
	Detail       string   `json:"detail"`
	Version      string   `json:"version"`
	AllowedTools []string `json:"allowedTools"`
}

func ToSkillInfoResponse(item domain.SkillInfo) SkillInfoResponse {
	versions := item.AvailableVersions
	if versions == nil {
		versions = []string{}
	}
	return SkillInfoResponse{
		Name:              item.Name,
		Namespace:         item.Namespace,
		Description:       item.Description,
		Version:           item.Version,
		Filename:          item.Filename,
		AvailableVersions: versions,
	}
}

func ToSkillDetailResponse(item domain.SkillDetail) SkillDetailResponse {
	versions := item.AvailableVersions
	if versions == nil {
		versions = []string{}
	}
	tools := item.AllowedTools
	if tools == nil {
		tools = []string{}
	}
	dirs := item.ResourceDirs
	if dirs == nil {
		dirs = []string{}
	}
	scripts := make([]SkillScriptInfoResponse, 0, len(item.Scripts))
	for _, s := range item.Scripts {
		scripts = append(scripts, SkillScriptInfoResponse{
			ScriptName:  s.ScriptName,
			Interpreter: s.Interpreter,
		})
	}
	return SkillDetailResponse{
		Name:              item.Name,
		Namespace:         item.Namespace,
		Description:       item.Description,
		Detail:            item.Detail,
		Version:           item.Version,
		Filename:          item.Filename,
		AvailableVersions: versions,
		AllowedTools:      tools,
		Scripts:           scripts,
		ResourceDirs:      dirs,
	}
}

func ToSkillNamespaceResponse(item domain.SkillNamespace) SkillNamespaceResponse {
	return SkillNamespaceResponse{
		ID:         item.ID,
		Visibility: item.Visibility,
	}
}
