package usecase

import (
	"context"
	"log/slog"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

type namespaceUsecase struct {
	repo domain.NamespaceRepository
	logger *slog.Logger
}

func NewNamespaceUsecase(repo domain.NamespaceRepository, logger *slog.Logger) domain.NamespaceUsecase {
	return &namespaceUsecase{repo: repo, logger: logger}
}

func (u *namespaceUsecase) List(ctx context.Context) ([]*entity.Namespace, error) {
	return u.repo.List(ctx)
}


