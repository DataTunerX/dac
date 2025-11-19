package types

import "time"

// AgentContainer represents an agent container resource
type AgentContainer struct {
	Name                  string                 `json:"name"`
	Namespace             string                 `json:"namespace"`
	Labels                map[string]string      `json:"labels,omitempty"`
	DataPolicy            DataPolicy             `json:"data_policy,omitempty"`             // From spec - what user configured
	ActiveDataDescriptors []ActiveDataDescriptor `json:"active_data_descriptors,omitempty"` // From status - actual running state
	Endpoint              *Endpoint              `json:"endpoint,omitempty"`
	CreatedAt             time.Time              `json:"created_at"`
}

// ActiveDataDescriptor tracks which data descriptors are being used
type ActiveDataDescriptor struct {
	Name       string `json:"name"`
	Namespace  string `json:"namespace"`
	LastSynced string `json:"last_synced"`
}

// DataDescriptor represents a data descriptor resource
type DataDescriptor struct {
	Name           string            `json:"name"`
	Namespace      string            `json:"namespace"`
	Labels         map[string]string `json:"labels,omitempty"`
	DescriptorType string            `json:"descriptor_type"`
	Sources        []DataSource      `json:"sources,omitempty"`
	SourceStatuses []SourceStatus    `json:"source_statuses,omitempty"`
	OverallPhase   string            `json:"overall_phase"`
	CreatedAt      time.Time         `json:"created_at"`
}

// DataSource represents a data source configuration
type DataSource struct {
	Type           string            `json:"type"`
	Name           string            `json:"name"`
	Metadata       map[string]string `json:"metadata,omitempty"`
	Extract        *ExtractConfig    `json:"extract,omitempty"`
	Prompts        *PromptsConfig    `json:"prompts,omitempty"`
	Processing     ProcessingConfig  `json:"processing,omitempty"`
	Classification []Classification  `json:"classification,omitempty"`
}

// ExtractConfig defines extraction configuration
type ExtractConfig struct {
	Tables []string `json:"tables,omitempty"`
	Querys []string `json:"querys,omitempty"`
}

// PromptsConfig defines prompts configuration
type PromptsConfig struct {
	ConfigMapName string `json:"configMapName"`
}

// ProcessingConfig defines data processing rules
type ProcessingConfig struct {
	Cleaning []CleaningRule `json:"cleaning,omitempty"`
}

// CleaningRule defines a single data cleaning rule
type CleaningRule struct {
	Rule   string            `json:"rule"`
	Params map[string]string `json:"params,omitempty"`
}

// Classification defines how data is categorized
type Classification struct {
	Domain      string                `json:"domain"`
	Category    string                `json:"category"`
	Subcategory string                `json:"subcategory"`
	Tags        []map[string][]string `json:"tags,omitempty"`
}

// DataPolicy defines how data sources should be selected
type DataPolicy struct {
	SourceNameSelector []string `json:"source_name_selector"`
}

// AgentCard defines the agent's metadata and capabilities
type AgentCard struct {
	Name        string       `json:"name"`
	Description string       `json:"description"`
	Skills      []AgentSkill `json:"skills,omitempty"`
}

// AgentSkill defines a specific skill the agent provides
type AgentSkill struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Tags        []string `json:"tags,omitempty"`
	Examples    []string `json:"examples,omitempty"`
}

// ModelSpec defines the LLM and embedding models to use
type ModelSpec struct {
	Embedding  string `json:"embedding"`
	ExpertLLM  string `json:"expertLLM"`
	PlannerLLM string `json:"plannerLLM"`
}

// SourceStatus represents the status of a data source
type SourceStatus struct {
	Name         string `json:"name"`
	Phase        string `json:"phase"`
	LastSyncTime string `json:"last_sync_time"`
	Records      int64  `json:"records"`
}

// Endpoint represents service endpoint information
type Endpoint struct {
	Address  string `json:"address"`
	Port     int32  `json:"port"`
	Protocol string `json:"protocol"`
}

// APIResponse represents a generic API response with typed data
type APIResponse[T any] struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Data    T      `json:"data"`
}

// ListData represents a generic list data structure
type ListData[T any] struct {
	Items []T `json:"items"`
	Total int `json:"total"`
}
