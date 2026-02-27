package dto

import (
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

type CreateConfigMapRequest struct {
	Name   string            `json:"name" validate:"required"`
	Type   string            `json:"type" validate:"required"` // llm|prompts
	Labels map[string]string `json:"labels"`
	Data   map[string]string `json:"data"`
}

type UpdateConfigMapRequest struct {
	Type   *string           `json:"type,omitempty"` // llm|prompts
	Labels map[string]string `json:"labels,omitempty"`
	Data   map[string]string `json:"data,omitempty"`
}

type ConfigMapResponse struct {
	Name      string            `json:"name"`
	Namespace string            `json:"namespace"`
	Labels    map[string]string `json:"labels,omitempty"`
	Data      map[string]string `json:"data,omitempty"`
	CreatedAt time.Time         `json:"created_at"`
}

func ToConfigMapResponse(cm *entity.ConfigMap) ConfigMapResponse {
	if cm == nil {
		return ConfigMapResponse{}
	}
	return ConfigMapResponse{
		Name:      cm.Name,
		Namespace: cm.Namespace,
		Labels:    cm.Labels,
		Data:      cm.Data,
		CreatedAt: cm.CreatedAt,
	}
}

func ParseConfigMapType(s string) (domain.ConfigMapType, error) {
	switch s {
	case string(domain.ConfigMapTypeLLM):
		return domain.ConfigMapTypeLLM, nil
	case string(domain.ConfigMapTypePrompts):
		return domain.ConfigMapTypePrompts, nil
	default:
		return "", domain.NewInvalidInputError("invalid configmap type")
	}
}

