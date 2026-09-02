package entity

import "time"

// AgentContainer represents a data agent container in the domain
type AgentContainer struct {
	// Metadata
	Name      string
	Namespace string
	Labels    map[string]string

	// Spec
	DACType                   string
	DataPolicy                DataPolicy
	SkillPolicy               SkillPolicy // skill DAC: raw skill-hub selection
	AgentCard                 AgentCard
	Model                     ModelSpec
	ExpertAgentMaxSteps       string
	OrchestratorAgentMaxLoops string
	SkillAgentMaxLoops        string

	// Status
	ActiveDataDescriptors []ActiveDataDescriptor
	Endpoint              *Endpoint
	Conditions            []Condition

	// Timestamps
	CreatedAt time.Time
	UpdatedAt time.Time
}

// DataPolicy defines how data sources should be selected
type DataPolicy struct {
	DataSourceType     string
	SemanticGroupID    string
	SourceNameSelector []string
}

// SkillPolicy binds skill-hub packages for dacType=skill.
type SkillPolicy struct {
	Skills []SkillRef
}

// SkillRef is a skill-hub package reference (namespace/name/version).
type SkillRef struct {
	Namespace string
	Name      string
	Version   string
}

// AgentCard defines the agent's metadata and capabilities
type AgentCard struct {
	Name        string
	Description string
	Skills      []AgentSkill
}

// AgentSkill defines a specific skill the agent provides
type AgentSkill struct {
	ID          string
	Name        string
	Description string
	Tags        []string
	Examples    []string
}

// ModelSpec defines the LLM and embedding models to use
type ModelSpec struct {
	Embedding  string
	ExpertLLM  string
	PlannerLLM string
}

// ActiveDataDescriptor tracks which data descriptors are being used
type ActiveDataDescriptor struct {
	Name       string
	Namespace  string
	LastSynced string
}

// Endpoint defines how to connect to the agent
type Endpoint struct {
	Address  string
	Port     int32
	Protocol string
}

// Condition represents the status condition
type Condition struct {
	Type               string
	Status             string
	LastTransitionTime time.Time
	Reason             string
	Message            string
}
