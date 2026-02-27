package dto

import "github.com/lvyanru/dac-apiserver/internal/domain"

type StartDiscoveryScanRequest struct {
	Target      string `json:"target" validate:"required"`
	PortsSpec   string `json:"portsSpec"`
	TimeoutMs   int    `json:"timeoutMs"`
	Concurrency int    `json:"concurrency"`
}

type StartDiscoveryScanResponse struct {
	ID     string                 `json:"id"`
	Status domain.DiscoveryJobStatus `json:"status"`
}

type DiscoveryJobResponse struct {
	ID         string                 `json:"id"`
	Name       string                 `json:"name,omitempty"`
	Target     string                 `json:"target"`
	PortsSpec  string                 `json:"portsSpec,omitempty"`
	Status     domain.DiscoveryJobStatus `json:"status"`
	Error      string                 `json:"error,omitempty"`
	StartedAt  *int64                 `json:"startedAt,omitempty"`
	FinishedAt *int64                 `json:"finishedAt,omitempty"`
	Services   []domain.DiscoveredService `json:"services,omitempty"`
}

type ListDiscoveryScansResponse struct {
	Items      []DiscoveryJobResponse `json:"items"`
	TotalCount int                    `json:"totalCount"`
}

type UpdateDiscoveryScanRequest struct {
	Name string `json:"name" validate:"required"`
}
