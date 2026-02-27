package domain

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// ConfigMapType represents DAC-managed configmap categories.
// Supported values are aligned with frontend filters: llm | prompts.
type ConfigMapType string

const (
	ConfigMapTypeLLM     ConfigMapType = "llm"
	ConfigMapTypePrompts ConfigMapType = "prompts"
)

func (t ConfigMapType) IsValid() bool {
	return t == ConfigMapTypeLLM || t == ConfigMapTypePrompts
}

// CreateConfigMapRequest defines create payload in usecase layer.
type CreateConfigMapRequest struct {
	Namespace string
	Name      string
	Type      ConfigMapType
	Labels    map[string]string
	Data      map[string]string
}

// UpdateConfigMapRequest defines update payload in usecase layer.
type UpdateConfigMapRequest struct {
	Type   *ConfigMapType
	Labels map[string]string
	Data   map[string]string
}

// ConfigMapListOptions defines list filters.
type ConfigMapListOptions struct {
	Type          ConfigMapType
	LabelSelector string
	Offset        int
	Limit         int
}

// ConfigMapRepository abstracts configmap persistence (k8s).
type ConfigMapRepository interface {
	Create(ctx context.Context, cm *entity.ConfigMap, t ConfigMapType) (*entity.ConfigMap, error)
	Get(ctx context.Context, namespace, name string) (*entity.ConfigMap, error)
	List(ctx context.Context, namespace string, opts ConfigMapListOptions) ([]*entity.ConfigMap, error)
	Update(ctx context.Context, cm *entity.ConfigMap, t ConfigMapType) (*entity.ConfigMap, error)
	Delete(ctx context.Context, namespace, name string) error
}

// ConfigMapUsecase defines configmap operations.
type ConfigMapUsecase interface {
	Create(ctx context.Context, req *CreateConfigMapRequest) (*entity.ConfigMap, error)
	Get(ctx context.Context, namespace, name string) (*entity.ConfigMap, error)
	List(ctx context.Context, namespace string, opts ConfigMapListOptions) ([]*entity.ConfigMap, error)
	Update(ctx context.Context, namespace, name string, req *UpdateConfigMapRequest) (*entity.ConfigMap, error)
	Delete(ctx context.Context, namespace, name string) error
}

