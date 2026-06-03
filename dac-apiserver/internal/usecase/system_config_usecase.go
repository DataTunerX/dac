package usecase

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type systemConfigUsecase struct {
	repo   domain.SystemConfigRepository
	logger *slog.Logger
	now    func() time.Time
}

func NewSystemConfigUsecase(repo domain.SystemConfigRepository, logger *slog.Logger) domain.SystemConfigUsecase {
	return &systemConfigUsecase{
		repo:   repo,
		logger: logger,
		now:    time.Now,
	}
}

func (u *systemConfigUsecase) List(ctx context.Context) ([]*domain.SystemConfiguration, error) {
	out := make([]*domain.SystemConfiguration, 0, 2)
	for _, name := range []domain.SystemConfigName{domain.SystemConfigDAC, domain.SystemConfigDD} {
		cfg, err := u.Get(ctx, name)
		if err != nil {
			return nil, err
		}
		out = append(out, cfg)
	}
	return out, nil
}

func (u *systemConfigUsecase) Get(ctx context.Context, name domain.SystemConfigName) (*domain.SystemConfiguration, error) {
	if !name.IsValid() {
		return nil, domain.NewInvalidInputError("invalid system configuration name")
	}

	raw, err := u.repo.Get(ctx, string(name))
	if err != nil {
		if domain.IsNotFound(err) {
			return &domain.SystemConfiguration{
				Name:      string(name),
				Namespace: domain.SystemConfigNamespace,
				Data:      map[string]string{},
				Exists:    false,
			}, nil
		}
		return nil, err
	}

	return toSystemConfiguration(raw, exposedKeysFor(name)), nil
}

func (u *systemConfigUsecase) ListVersions(ctx context.Context, name domain.SystemConfigName) ([]*domain.SystemConfigurationVersion, error) {
	if !name.IsValid() {
		return nil, domain.NewInvalidInputError("invalid system configuration name")
	}

	archives, err := u.repo.ListArchives(ctx, string(name))
	if err != nil {
		return nil, fmt.Errorf("list configuration versions: %w", err)
	}

	out := make([]*domain.SystemConfigurationVersion, 0, len(archives))
	for _, raw := range archives {
		out = append(out, toSystemConfigurationVersion(raw, exposedKeysFor(name)))
	}
	return out, nil
}

func (u *systemConfigUsecase) GetVersion(ctx context.Context, name domain.SystemConfigName, version string) (*domain.SystemConfigurationVersion, error) {
	if !name.IsValid() {
		return nil, domain.NewInvalidInputError("invalid system configuration name")
	}
	version = strings.TrimSpace(version)
	if version == "" {
		return nil, domain.NewInvalidInputError("version is required")
	}

	archiveName := fmt.Sprintf("%s-%s", name, version)
	raw, err := u.repo.Get(ctx, archiveName)
	if err != nil {
		return nil, err
	}
	if raw.Labels == nil ||
		raw.Labels[domain.SystemConfigArchiveLabel] != "true" ||
		raw.Labels[domain.SystemConfigSourceLabel] != string(name) {
		return nil, domain.NewNotFoundError("SystemConfigurationVersion", version)
	}

	return toSystemConfigurationVersion(raw, exposedKeysFor(name)), nil
}

func (u *systemConfigUsecase) Update(ctx context.Context, name domain.SystemConfigName, req *domain.UpdateSystemConfigurationRequest) (*domain.SystemConfiguration, error) {
	if !name.IsValid() {
		return nil, domain.NewInvalidInputError("invalid system configuration name")
	}
	if req == nil || req.Data == nil {
		return nil, domain.NewInvalidInputError("data is required")
	}

	exposedKeys := exposedKeysFor(name)
	if err := validateExposedUpdate(req.Data, exposedKeys); err != nil {
		return nil, err
	}

	existing, err := u.repo.Get(ctx, string(name))
	if err != nil && !domain.IsNotFound(err) {
		return nil, err
	}

	if existing != nil {
		if strings.TrimSpace(req.ResourceVersion) == "" {
			return nil, domain.NewInvalidInputError("resourceVersion is required when updating an existing configuration")
		}
		if req.ResourceVersion != existing.ResourceVersion {
			return nil, domain.NewConflictError(
				fmt.Sprintf("configuration %q was modified; refresh and retry with the latest resourceVersion", name),
			)
		}
	} else if strings.TrimSpace(req.ResourceVersion) != "" {
		return nil, domain.NewConflictError(
			fmt.Sprintf("configuration %q does not exist; omit resourceVersion to create it", name),
		)
	}

	version := newArchiveVersion(u.now())

	if existing != nil {
		if err := u.archiveCurrent(ctx, existing, string(name), version); err != nil {
			return nil, err
		}

		merged := mergeExposedData(existing.Data, req.Data, exposedKeys)
		updated, err := u.repo.Replace(ctx, &domain.RawSystemConfigMap{
			Name:            string(name),
			Labels:          existing.Labels,
			Data:            merged,
			ResourceVersion: existing.ResourceVersion,
		})
		if err != nil {
			u.deleteArchiveBestEffort(ctx, string(name), version)
			return nil, fmt.Errorf("update active configuration: %w", err)
		}

		if u.logger != nil {
			u.logger.Info("system configuration updated",
				"name", name,
				"version", version,
				"namespace", domain.SystemConfigNamespace,
			)
		}
		return toSystemConfiguration(updated, exposedKeys), nil
	}

	merged := mergeExposedData(map[string]string{}, req.Data, exposedKeys)
	created, err := u.repo.Create(ctx, &domain.RawSystemConfigMap{
		Name:   string(name),
		Labels: map[string]string{},
		Data:   merged,
	})
	if err != nil {
		return nil, fmt.Errorf("create active configuration: %w", err)
	}

	if u.logger != nil {
		u.logger.Info("system configuration created",
			"name", name,
			"namespace", domain.SystemConfigNamespace,
		)
	}
	return toSystemConfiguration(created, exposedKeys), nil
}

func (u *systemConfigUsecase) archiveCurrent(ctx context.Context, existing *domain.RawSystemConfigMap, sourceName, version string) error {
	labels := cloneStringMap(existing.Labels)
	if labels == nil {
		labels = map[string]string{}
	}
	labels[domain.SystemConfigArchiveLabel] = "true"
	labels[domain.SystemConfigSourceLabel] = sourceName
	labels[domain.SystemConfigVersionLabel] = version

	archiveName := fmt.Sprintf("%s-%s", sourceName, version)
	_, err := u.repo.Create(ctx, &domain.RawSystemConfigMap{
		Name:   archiveName,
		Labels: labels,
		Data:   cloneStringMap(existing.Data),
	})
	if err != nil {
		return fmt.Errorf("archive configuration %s: %w", sourceName, err)
	}
	return nil
}

func (u *systemConfigUsecase) deleteArchiveBestEffort(ctx context.Context, sourceName, version string) {
	archiveName := fmt.Sprintf("%s-%s", sourceName, version)
	if err := u.repo.Delete(ctx, archiveName, ""); err != nil && u.logger != nil {
		u.logger.Warn("failed to delete orphan configuration archive after failed update",
			"archive", archiveName,
			"error", err,
		)
	}
}

func newArchiveVersion(now time.Time) string {
	t := now.UTC()
	return fmt.Sprintf("%s%09d", t.Format("20060102150405"), t.Nanosecond())
}

func exposedKeysFor(name domain.SystemConfigName) []string {
	switch name {
	case domain.SystemConfigDD:
		return domain.DDConfigurationExposedKeys
	default:
		return domain.DACConfigurationExposedKeys
	}
}

func validateExposedUpdate(data map[string]string, allowed []string) error {
	allowedSet := make(map[string]struct{}, len(allowed))
	for _, k := range allowed {
		allowedSet[k] = struct{}{}
	}
	for k := range data {
		if _, ok := allowedSet[k]; !ok {
			return domain.NewInvalidInputError(fmt.Sprintf("field %q is not allowed for this configuration", k))
		}
	}
	return nil
}

func mergeExposedData(base, updates map[string]string, exposedKeys []string) map[string]string {
	out := cloneStringMap(base)
	if out == nil {
		out = map[string]string{}
	}
	for _, k := range exposedKeys {
		if v, ok := updates[k]; ok {
			out[k] = v
		}
	}
	return out
}

func toSystemConfiguration(raw *domain.RawSystemConfigMap, exposedKeys []string) *domain.SystemConfiguration {
	return &domain.SystemConfiguration{
		Name:            raw.Name,
		Namespace:       raw.Namespace,
		Data:            pickExposedData(raw.Data, exposedKeys),
		ResourceVersion: raw.ResourceVersion,
		Exists:          true,
		CreatedAt:       raw.CreationTimestamp,
	}
}

func toSystemConfigurationVersion(raw *domain.RawSystemConfigMap, exposedKeys []string) *domain.SystemConfigurationVersion {
	version := ""
	if raw.Labels != nil {
		version = raw.Labels[domain.SystemConfigVersionLabel]
	}
	if version == "" {
		source := ""
		if raw.Labels != nil {
			source = raw.Labels[domain.SystemConfigSourceLabel]
		}
		if source != "" && strings.HasPrefix(raw.Name, source+"-") {
			version = strings.TrimPrefix(raw.Name, source+"-")
		}
	}
	return &domain.SystemConfigurationVersion{
		Name:      raw.Name,
		Version:   version,
		Namespace: raw.Namespace,
		Data:      pickExposedData(raw.Data, exposedKeys),
		CreatedAt: raw.CreationTimestamp,
	}
}

func pickExposedData(data map[string]string, exposedKeys []string) map[string]string {
	out := make(map[string]string, len(exposedKeys))
	for _, k := range exposedKeys {
		if v, ok := data[k]; ok {
			out[k] = v
		}
	}
	return out
}

func cloneStringMap(in map[string]string) map[string]string {
	if in == nil {
		return nil
	}
	out := make(map[string]string, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}
