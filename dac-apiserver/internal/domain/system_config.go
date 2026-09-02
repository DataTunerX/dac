package domain

import (
	"context"
	"time"
)

const (
	// SystemConfigNamespace is where cluster-wide dac/dd configuration ConfigMaps live.
	SystemConfigNamespace = "dac"

	DACConfigurationName = "dac-configuration"
	DDConfigurationName  = "dd-configuration"

	SystemConfigArchiveLabel = "dac.io/system-config-archive"
	SystemConfigSourceLabel  = "dac.io/system-config-source"
	SystemConfigVersionLabel = "dac.io/system-config-version"
)

// SystemConfigName identifies a managed cluster configuration ConfigMap.
type SystemConfigName string

const (
	SystemConfigDAC SystemConfigName = DACConfigurationName
	SystemConfigDD  SystemConfigName = DDConfigurationName
)

func (n SystemConfigName) IsValid() bool {
	return n == SystemConfigDAC || n == SystemConfigDD
}

// Exposed keys for API responses and updates (images + LLM defaults only).
var (
	DACConfigurationExposedKeys = []string{
		"orchestrator-agent-image",
		"expert-agent-image",
		"ds-data-services-image",
		"code-agent-image",
		"doc-agent-image",
		"dd-sync-observer-image",
		"skill-agent-image",
		"default-planner-llm",
		"default-expert-llm",
		"cross-sg-max-hop",
	}
	DDConfigurationExposedKeys = []string{
		"data-sinker-job-image",
		"data-sinker-status-image",
		"dac-data-services-image",
		"llm-config",
	}
)

// SystemConfiguration is the active cluster configuration (exposed fields only).
type SystemConfiguration struct {
	Name            string            `json:"name"`
	Namespace       string            `json:"namespace"`
	Data            map[string]string `json:"data"`
	ResourceVersion string            `json:"resourceVersion,omitempty"`
	Exists          bool              `json:"exists"`
	CreatedAt       time.Time         `json:"createdAt,omitempty"`
}

// SystemConfigurationVersion is an archived snapshot of a configuration ConfigMap.
type SystemConfigurationVersion struct {
	Name      string            `json:"name"`
	Version   string            `json:"version"`
	Namespace string            `json:"namespace"`
	Data      map[string]string `json:"data"`
	CreatedAt time.Time         `json:"createdAt"`
}

// UpdateSystemConfigurationRequest carries exposed-field updates for a configuration.
// ResourceVersion must match the active ConfigMap (from GET/LIST) for optimistic concurrency.
type UpdateSystemConfigurationRequest struct {
	Data            map[string]string `json:"data"`
	ResourceVersion string            `json:"resourceVersion"`
}

// SystemConfigRepository persists dac-configuration / dd-configuration ConfigMaps.
type SystemConfigRepository interface {
	Get(ctx context.Context, name string) (*RawSystemConfigMap, error)
	ListArchives(ctx context.Context, sourceName string) ([]*RawSystemConfigMap, error)
	Create(ctx context.Context, cm *RawSystemConfigMap) (*RawSystemConfigMap, error)
	// Replace updates an existing ConfigMap in place (atomic at the Kubernetes object level).
	Replace(ctx context.Context, cm *RawSystemConfigMap) (*RawSystemConfigMap, error)
	Delete(ctx context.Context, name, resourceVersion string) error
}

// RawSystemConfigMap is the full ConfigMap as stored in Kubernetes.
type RawSystemConfigMap struct {
	Name              string
	Namespace         string
	Labels            map[string]string
	Data              map[string]string
	ResourceVersion   string
	CreationTimestamp time.Time
}

// SystemConfigUsecase manages cluster system configuration with versioned updates.
type SystemConfigUsecase interface {
	List(ctx context.Context) ([]*SystemConfiguration, error)
	Get(ctx context.Context, name SystemConfigName) (*SystemConfiguration, error)
	ListVersions(ctx context.Context, name SystemConfigName) ([]*SystemConfigurationVersion, error)
	GetVersion(ctx context.Context, name SystemConfigName, version string) (*SystemConfigurationVersion, error)
	Update(ctx context.Context, name SystemConfigName, req *UpdateSystemConfigurationRequest) (*SystemConfiguration, error)
}
