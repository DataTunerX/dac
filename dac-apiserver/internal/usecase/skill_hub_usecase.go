package usecase

import (
	"context"
	"io"
	"log/slog"
	"strings"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type skillHubUsecase struct {
	client domain.SkillHubClient
	logger *slog.Logger
}

func NewSkillHubUsecase(client domain.SkillHubClient, logger *slog.Logger) domain.SkillHubUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &skillHubUsecase{client: client, logger: logger}
}

func (u *skillHubUsecase) ListNamespaces(ctx context.Context) ([]domain.SkillNamespace, error) {
	return u.client.ListNamespaces(ctx)
}

func (u *skillHubUsecase) NamespaceExists(ctx context.Context, namespace string) (bool, error) {
	namespace = strings.TrimSpace(namespace)
	if namespace == "" {
		return false, domain.NewInvalidInputError("namespace is required")
	}
	return u.client.NamespaceExists(ctx, namespace)
}

func (u *skillHubUsecase) CreateNamespace(ctx context.Context, namespace string) (*domain.SkillNamespace, error) {
	namespace = strings.TrimSpace(namespace)
	if namespace == "" {
		return nil, domain.NewInvalidInputError("namespace is required")
	}
	return u.client.CreateNamespace(ctx, namespace)
}

func (u *skillHubUsecase) DeleteNamespace(ctx context.Context, namespace string) error {
	namespace = strings.TrimSpace(namespace)
	if namespace == "" {
		return domain.NewInvalidInputError("namespace is required")
	}
	return u.client.DeleteNamespace(ctx, namespace)
}

func (u *skillHubUsecase) ListSkills(ctx context.Context, namespace string) ([]domain.SkillInfo, error) {
	namespace = strings.TrimSpace(namespace)
	if namespace == "" {
		return nil, domain.NewInvalidInputError("namespace is required")
	}
	return u.client.ListSkills(ctx, namespace)
}

// GetSkill returns zip-backed pack fields (detail, allowed_tools, scripts, …).
// Empty version means "latest" — resolved by skill-hub.
func (u *skillHubUsecase) GetSkill(ctx context.Context, namespace, name, version string) (*domain.SkillDetail, error) {
	namespace = strings.TrimSpace(namespace)
	name = strings.TrimSpace(name)
	version = strings.TrimSpace(version)
	if namespace == "" {
		return nil, domain.NewInvalidInputError("namespace is required")
	}
	if name == "" {
		return nil, domain.NewInvalidInputError("skill name is required")
	}
	return u.client.GetSkill(ctx, namespace, name, version)
}

func (u *skillHubUsecase) CreateSkill(ctx context.Context, namespace string, req domain.CreateSkillRequest) (*domain.SkillInfo, error) {
	namespace = strings.TrimSpace(namespace)
	req.Name = strings.TrimSpace(req.Name)
	req.Description = strings.TrimSpace(req.Description)
	req.Version = strings.TrimSpace(req.Version)
	if namespace == "" {
		return nil, domain.NewInvalidInputError("namespace is required")
	}
	if req.Name == "" {
		return nil, domain.NewInvalidInputError("name is required")
	}
	if req.Description == "" {
		return nil, domain.NewInvalidInputError("description is required")
	}
	if req.Version == "" {
		req.Version = "1.0.0"
	}
	if req.AllowedTools == nil {
		req.AllowedTools = []string{}
	}
	return u.client.CreateSkill(ctx, namespace, req)
}

func (u *skillHubUsecase) UploadSkill(ctx context.Context, namespace, filename string, r io.Reader) (*domain.SkillInfo, error) {
	namespace = strings.TrimSpace(namespace)
	filename = strings.TrimSpace(filename)
	if namespace == "" {
		return nil, domain.NewInvalidInputError("namespace is required")
	}
	if filename == "" {
		return nil, domain.NewInvalidInputError("filename is required")
	}
	if r == nil {
		return nil, domain.NewInvalidInputError("file is required")
	}
	return u.client.UploadSkill(ctx, namespace, filename, r)
}

func (u *skillHubUsecase) DownloadSkill(ctx context.Context, namespace, name, version string) (*domain.SkillDownload, error) {
	namespace = strings.TrimSpace(namespace)
	name = strings.TrimSpace(name)
	version = strings.TrimSpace(version)
	if namespace == "" {
		return nil, domain.NewInvalidInputError("namespace is required")
	}
	if name == "" {
		return nil, domain.NewInvalidInputError("skill name is required")
	}
	return u.client.DownloadSkill(ctx, namespace, name, version)
}

func (u *skillHubUsecase) DeleteSkill(ctx context.Context, namespace, name, version string) error {
	namespace = strings.TrimSpace(namespace)
	name = strings.TrimSpace(name)
	version = strings.TrimSpace(version)
	if namespace == "" {
		return domain.NewInvalidInputError("namespace is required")
	}
	if name == "" {
		return domain.NewInvalidInputError("skill name is required")
	}
	return u.client.DeleteSkill(ctx, namespace, name, version)
}

func (u *skillHubUsecase) Reload(ctx context.Context) ([]domain.SkillInfo, error) {
	return u.client.Reload(ctx)
}
