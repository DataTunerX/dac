package dto

import (
	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type SystemConfigurationResponse struct {
	Name            string            `json:"name"`
	Namespace       string            `json:"namespace"`
	Data            map[string]string `json:"data"`
	ResourceVersion string            `json:"resourceVersion,omitempty"`
	Exists          bool              `json:"exists"`
	CreatedAt       string            `json:"createdAt,omitempty"`
}

type SystemConfigurationVersionResponse struct {
	Name      string            `json:"name"`
	Version   string            `json:"version"`
	Namespace string            `json:"namespace"`
	Data      map[string]string `json:"data"`
	CreatedAt string            `json:"createdAt"`
}

type UpdateSystemConfigurationRequest struct {
	Data            map[string]string `json:"data" binding:"required"`
	ResourceVersion string            `json:"resourceVersion"`
}

func ToSystemConfigurationResponse(cfg *domain.SystemConfiguration) SystemConfigurationResponse {
	resp := SystemConfigurationResponse{
		Name:            cfg.Name,
		Namespace:       cfg.Namespace,
		Data:            cfg.Data,
		ResourceVersion: cfg.ResourceVersion,
		Exists:          cfg.Exists,
	}
	if !cfg.CreatedAt.IsZero() {
		resp.CreatedAt = cfg.CreatedAt.UTC().Format(timeRFC3339)
	}
	return resp
}

func ToSystemConfigurationVersionResponse(v *domain.SystemConfigurationVersion) SystemConfigurationVersionResponse {
	return SystemConfigurationVersionResponse{
		Name:      v.Name,
		Version:   v.Version,
		Namespace: v.Namespace,
		Data:      v.Data,
		CreatedAt: v.CreatedAt.UTC().Format(timeRFC3339),
	}
}

const timeRFC3339 = "2006-01-02T15:04:05Z07:00"
