package domain

import (
	"context"
	"io"
)

// SkillHubBaseURL is the in-cluster skill-hub Service (namespace dac).
const SkillHubBaseURL = "http://skill-hub.dac.svc.cluster.local:8000"

// SkillInfo is a skill package indexed by skill-hub.
type SkillInfo struct {
	Name              string
	Namespace         string
	Description       string
	Version           string
	Filename          string
	AvailableVersions []string
}

// SkillScriptInfo is a script entry from a skill pack.
type SkillScriptInfo struct {
	ScriptName  string
	Interpreter string
}

// SkillDetail is full skill pack metadata (SKILL.md body + _meta.json fields).
type SkillDetail struct {
	Name              string
	Namespace         string
	Description       string
	Detail            string
	Version           string
	Filename          string
	AvailableVersions []string
	AllowedTools      []string
	Scripts           []SkillScriptInfo
	ResourceDirs      []string
}

// SkillNamespace is a skill-hub namespace (tenant space for skill zips).
type SkillNamespace struct {
	ID         string
	Visibility string
}

// SkillDownload is a binary zip payload streamed from skill-hub.
type SkillDownload struct {
	Filename string
	Version  string
	Body     io.ReadCloser
	Size     int64
}

// CreateSkillRequest is the structured payload for creating a skill without a zip.
// skill-hub packages these fields into SKILL.md + _meta.json (slug is always name).
type CreateSkillRequest struct {
	Name         string
	Description  string
	Detail       string
	Version      string
	AllowedTools []string
}

// SkillHubClient talks to the skill-hub HTTP registry.
type SkillHubClient interface {
	ListNamespaces(ctx context.Context) ([]SkillNamespace, error)
	NamespaceExists(ctx context.Context, namespace string) (bool, error)
	CreateNamespace(ctx context.Context, namespace string) (*SkillNamespace, error)
	DeleteNamespace(ctx context.Context, namespace string) error

	ListSkills(ctx context.Context, namespace string) ([]SkillInfo, error)
	GetSkill(ctx context.Context, namespace, name, version string) (*SkillDetail, error)
	CreateSkill(ctx context.Context, namespace string, req CreateSkillRequest) (*SkillInfo, error)
	// UpdateSkill rewrites metadata in an existing pack (preserves scripts/resources).
	// sourceVersion selects which zip to edit (empty = latest); req.Version is written.
	UpdateSkill(ctx context.Context, namespace, name, sourceVersion string, req CreateSkillRequest) (*SkillInfo, error)
	UploadSkill(ctx context.Context, namespace, filename string, r io.Reader) (*SkillInfo, error)
	DownloadSkill(ctx context.Context, namespace, name, version string) (*SkillDownload, error)
	DeleteSkill(ctx context.Context, namespace, name, version string) error

	Reload(ctx context.Context) ([]SkillInfo, error)
}

// SkillHubUsecase exposes skill-hub management for the UI BFF.
type SkillHubUsecase interface {
	ListNamespaces(ctx context.Context) ([]SkillNamespace, error)
	NamespaceExists(ctx context.Context, namespace string) (bool, error)
	CreateNamespace(ctx context.Context, namespace string) (*SkillNamespace, error)
	DeleteNamespace(ctx context.Context, namespace string) error

	ListSkills(ctx context.Context, namespace string) ([]SkillInfo, error)
	GetSkill(ctx context.Context, namespace, name, version string) (*SkillDetail, error)
	CreateSkill(ctx context.Context, namespace string, req CreateSkillRequest) (*SkillInfo, error)
	UpdateSkill(ctx context.Context, namespace, name, sourceVersion string, req CreateSkillRequest) (*SkillInfo, error)
	UploadSkill(ctx context.Context, namespace, filename string, r io.Reader) (*SkillInfo, error)
	DownloadSkill(ctx context.Context, namespace, name, version string) (*SkillDownload, error)
	DeleteSkill(ctx context.Context, namespace, name, version string) error

	Reload(ctx context.Context) ([]SkillInfo, error)
}
