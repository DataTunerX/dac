package domain

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// NamespaceRepository abstracts k8s namespaces.
type NamespaceRepository interface {
	List(ctx context.Context) ([]*entity.Namespace, error)
}

type NamespaceUsecase interface {
	List(ctx context.Context) ([]*entity.Namespace, error)
}

