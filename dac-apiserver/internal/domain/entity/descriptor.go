package entity

import "time"

// DataDescriptor represents a data descriptor in the domain
type DataDescriptor struct {
	// Metadata
	Name      string
	Namespace string
	Labels    map[string]string

	// Spec
	DescriptorType string
	Sources        []DataSource

	// Status
	SourceStatuses []SourceStatus
	ConsumedBy     []ObjectReference
	OverallPhase   string
	Conditions     []Condition

	// Timestamps
	CreatedAt time.Time
	UpdatedAt time.Time
}

// DataSource defines a data source configuration
type DataSource struct {
	Type           string
	Name           string
	Metadata       map[string]string
	Extract        *ExtractConfig
	Prompts        *PromptsConfig
	Processing     ProcessingConfig
	Classification []Classification
}

// ExtractConfig defines extraction configuration
type ExtractConfig struct {
	Tables []string
	Querys []string
}

// PromptsConfig defines prompts configuration
type PromptsConfig struct {
	ConfigMapName string
}

// ProcessingConfig defines data processing rules
type ProcessingConfig struct {
	Cleaning []CleaningRule
}

// CleaningRule defines a single data cleaning rule
type CleaningRule struct {
	Rule   string
	Params map[string]string
}

// Classification defines how data is categorized
type Classification struct {
	Domain      string
	Category    string
	Subcategory string
	Tags        []map[string][]string
}

// SourceStatus defines the status of a data source
type SourceStatus struct {
	Name         string
	Phase        string
	LastSyncTime time.Time
	Records      int64
	TaskID       string
}

// ObjectReference contains information to identify a referenced object
type ObjectReference struct {
	Name      string
	Namespace string
}
