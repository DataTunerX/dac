package types

// CreateDACRequest represents a request to create a DataAgentContainer
type CreateDACRequest struct {
	Name                string            `json:"name"`
	Namespace           string            `json:"namespace"`
	Labels              map[string]string `json:"labels,omitempty"`
	DataPolicy          DataPolicy        `json:"dataPolicy"`
	AgentCard           AgentCard         `json:"agentCard"`
	Model               ModelSpec         `json:"model"`
	ExpertAgentMaxSteps string            `json:"expertAgentMaxSteps,omitempty"`
}

// CreateDDRequest represents a request to create a DataDescriptor
type CreateDDRequest struct {
	Name           string            `json:"name"`
	Namespace      string            `json:"namespace"`
	Labels         map[string]string `json:"labels,omitempty"`
	DescriptorType string            `json:"descriptorType"`
	Sources        []DataSource      `json:"sources"`
}
