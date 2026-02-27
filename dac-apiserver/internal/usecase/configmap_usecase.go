package usecase

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

type configMapUsecase struct {
	repo domain.ConfigMapRepository
	logger *slog.Logger
}

func NewConfigMapUsecase(repo domain.ConfigMapRepository, logger *slog.Logger) domain.ConfigMapUsecase {
	return &configMapUsecase{repo: repo, logger: logger}
}

func (u *configMapUsecase) Create(ctx context.Context, req *domain.CreateConfigMapRequest) (*entity.ConfigMap, error) {
	if err := u.validateCreate(req); err != nil {
		return nil, err
	}

	cm := &entity.ConfigMap{
		Name:      req.Name,
		Namespace: req.Namespace,
		Labels:    req.Labels,
		Data:      req.Data,
	}

	created, err := u.repo.Create(ctx, cm, req.Type)
	if err != nil {
		return nil, fmt.Errorf("failed to create configmap: %w", err)
	}
	return created, nil
}

func (u *configMapUsecase) Get(ctx context.Context, namespace, name string) (*entity.ConfigMap, error) {
	if namespace == "" || name == "" {
		return nil, domain.ErrInvalidInput
	}
	cm, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, fmt.Errorf("failed to get configmap: %w", err)
	}
	return cm, nil
}

func (u *configMapUsecase) List(ctx context.Context, namespace string, opts domain.ConfigMapListOptions) ([]*entity.ConfigMap, error) {
	if namespace == "" {
		return nil, domain.ErrInvalidInput
	}
	if opts.Type != "" && !opts.Type.IsValid() {
		return nil, domain.NewInvalidInputError("invalid configmap type")
	}
	items, err := u.repo.List(ctx, namespace, opts)
	if err != nil {
		return nil, fmt.Errorf("failed to list configmaps: %w", err)
	}
	return items, nil
}

func (u *configMapUsecase) Update(ctx context.Context, namespace, name string, req *domain.UpdateConfigMapRequest) (*entity.ConfigMap, error) {
	if namespace == "" || name == "" {
		return nil, domain.ErrInvalidInput
	}
	if req == nil {
		return nil, domain.ErrInvalidInput
	}
	if req.Type != nil && !req.Type.IsValid() {
		return nil, domain.NewInvalidInputError("invalid configmap type")
	}

	existing, err := u.repo.Get(ctx, namespace, name)
	if err != nil {
		return nil, fmt.Errorf("failed to get existing configmap: %w", err)
	}

	if req.Labels != nil {
		existing.Labels = req.Labels
	}
	if req.Data != nil {
		existing.Data = req.Data
	}

	cmType := domain.ConfigMapType("")
	if req.Type != nil {
		cmType = *req.Type
	}

	updated, err := u.repo.Update(ctx, existing, cmType)
	if err != nil {
		return nil, fmt.Errorf("failed to update configmap: %w", err)
	}
	return updated, nil
}

func (u *configMapUsecase) Delete(ctx context.Context, namespace, name string) error {
	if namespace == "" || name == "" {
		return domain.ErrInvalidInput
	}
	if err := u.repo.Delete(ctx, namespace, name); err != nil {
		return fmt.Errorf("failed to delete configmap: %w", err)
	}
	return nil
}

func (u *configMapUsecase) validateCreate(req *domain.CreateConfigMapRequest) error {
	if req == nil {
		return domain.ErrInvalidInput
	}
	if req.Namespace == "" {
		return domain.ErrInvalidInput
	}
	if req.Name == "" {
		return domain.ErrInvalidInput
	}
	if !req.Type.IsValid() {
		return domain.NewInvalidInputError("invalid configmap type")
	}
	// Data can be empty depending on type; validation is left to consumers.
	return nil
}
