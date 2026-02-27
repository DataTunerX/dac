package domain

import (
	"context"
	"time"
)

type DiscoveryJobStatus string

const (
	DiscoveryJobPending   DiscoveryJobStatus = "PENDING"
	DiscoveryJobRunning   DiscoveryJobStatus = "RUNNING"
	DiscoveryJobSucceeded DiscoveryJobStatus = "SUCCEEDED"
	DiscoveryJobFailed    DiscoveryJobStatus = "FAILED"
)

type DiscoveryUsecase interface {
	StartScan(ctx context.Context, req *StartDiscoveryScanRequest) (*DiscoveryJob, error)
	GetScan(ctx context.Context, id string) (*DiscoveryJob, error)
	ListScans(ctx context.Context, req *ListDiscoveryScansRequest) (*ListDiscoveryScansResult, error)
	UpdateScan(ctx context.Context, id string, req *UpdateDiscoveryScanRequest) (*DiscoveryJob, error)
	DeleteScan(ctx context.Context, id string) error
}

type StartDiscoveryScanRequest struct {
	Target     string
	PortsSpec  string
	Timeout    time.Duration
	Concurrency int
}

type DiscoveryJob struct {
	ID        string
	Name      string
	Target    string
	PortsSpec string
	Status    DiscoveryJobStatus
	Error     string
	StartedAt *time.Time
	FinishedAt *time.Time
	Services  []DiscoveredService
	CreatedAt time.Time
	UpdatedAt time.Time
}

type ListDiscoveryScansRequest struct {
	Target string
	Status DiscoveryJobStatus
	Limit  int
	Offset int
}

type ListDiscoveryScansResult struct {
	Items []*DiscoveryJob
	Total int
}

type UpdateDiscoveryScanRequest struct {
	Name string
}

type DiscoveredService struct {
	Host        string            `json:"host"`
	Port        int               `json:"port"`
	Protocol    string            `json:"protocol"`   // "tcp"
	ServiceType string            `json:"serviceType"` // "http"|"postgres"|"mysql"|"redis"|"unknown"
	Product     string            `json:"product,omitempty"`
	Version     string            `json:"version,omitempty"`
	TLS         bool              `json:"tls"`
	Metadata    map[string]string `json:"metadata,omitempty"` // headers/title/etc (small)
}

type DiscoveryJobRepository interface {
	Create(ctx context.Context, job *DiscoveryJob) error
	Update(ctx context.Context, job *DiscoveryJob) error
	Get(ctx context.Context, id string) (*DiscoveryJob, error)
	List(ctx context.Context, req *ListDiscoveryScansRequest) ([]*DiscoveryJob, int, error)
	Delete(ctx context.Context, id string) error
}

