package loader

import (
	"fmt"
	"os"

	"sigs.k8s.io/yaml"

	"github.com/lvyanru/dac-apiserver/internal/cli/types"
)

// ResourceFile represents a resource definition loaded from a YAML file
type ResourceFile struct {
	// Kind specifies the resource type: "DataAgentContainer" or "DataDescriptor"
	Kind string `yaml:"kind"`
	// Spec contains the resource specification
	Spec ResourceSpec `yaml:"spec"`
}

// ResourceSpec defines a unified resource specification
type ResourceSpec struct {
	// Fields for DataAgentContainer (DAC)
	Name                string            `yaml:"name,omitempty"`
	Namespace           string            `yaml:"namespace,omitempty"`
	Labels              map[string]string `yaml:"labels,omitempty"`
	DataPolicy          *types.DataPolicy `yaml:"dataPolicy,omitempty"`
	AgentCard           *types.AgentCard  `yaml:"agentCard,omitempty"`
	Model               *types.ModelSpec  `yaml:"model,omitempty"`
	ExpertAgentMaxSteps string            `yaml:"expertAgentMaxSteps,omitempty"`

	// Fields for DataDescriptor (DD)
	DescriptorType string             `yaml:"descriptorType,omitempty"`
	Sources        []types.DataSource `yaml:"sources,omitempty"`
}

// LoadFromFile loads a resource definition from a YAML file.
// Supports loading DataAgentContainer and DataDescriptor resources.
func LoadFromFile(filepath string) (*ResourceFile, error) {
	// Read file
	data, err := os.ReadFile(filepath)
	if err != nil {
		return nil, fmt.Errorf("failed to read file: %w", err)
	}

	// Parse YAML
	var resource ResourceFile
	if err := yaml.Unmarshal(data, &resource); err != nil {
		return nil, fmt.Errorf("failed to parse yaml: %w", err)
	}

	// Validate Kind field
	if resource.Kind == "" {
		return nil, fmt.Errorf("'kind' field is required")
	}

	// Validate resource type
	switch resource.Kind {
	case "DataAgentContainer", "DataDescriptor":
		// Valid resource type
	default:
		return nil, fmt.Errorf("invalid kind '%s', must be 'DataAgentContainer' or 'DataDescriptor'", resource.Kind)
	}

	return &resource, nil
}

// ToCreateDACRequest converts ResourceFile to CreateDACRequest
func (r *ResourceFile) ToCreateDACRequest() (*types.CreateDACRequest, error) {
	if r.Kind != "DataAgentContainer" {
		return nil, fmt.Errorf("resource kind is '%s', expected 'DataAgentContainer'", r.Kind)
	}

	// Validate required fields
	if r.Spec.Name == "" {
		return nil, fmt.Errorf("spec.name is required")
	}
	if r.Spec.Namespace == "" {
		return nil, fmt.Errorf("spec.namespace is required")
	}
	if r.Spec.DataPolicy == nil || len(r.Spec.DataPolicy.SourceNameSelector) == 0 {
		return nil, fmt.Errorf("spec.dataPolicy.sourceNameSelector is required")
	}

	// Set default values
	agentCard := r.Spec.AgentCard
	if agentCard == nil {
		agentCard = &types.AgentCard{
			Name:        r.Spec.Name,
			Description: fmt.Sprintf("Data Agent for %s", r.Spec.Name),
			Skills:      []types.AgentSkill{},
		}
	} else if agentCard.Name == "" {
		agentCard.Name = r.Spec.Name
	}

	model := r.Spec.Model
	if model == nil {
		// Use default model configuration
		model = &types.ModelSpec{
			ExpertLLM:  "qwen-max",
			PlannerLLM: "qwen-max",
			Embedding:  "text-embedding-v3",
		}
	}

	maxSteps := r.Spec.ExpertAgentMaxSteps
	if maxSteps == "" {
		maxSteps = "5"
	}

	return &types.CreateDACRequest{
		Name:                r.Spec.Name,
		Namespace:           r.Spec.Namespace,
		Labels:              r.Spec.Labels,
		DataPolicy:          *r.Spec.DataPolicy,
		AgentCard:           *agentCard,
		Model:               *model,
		ExpertAgentMaxSteps: maxSteps,
	}, nil
}

// ToCreateDDRequest converts ResourceFile to CreateDDRequest
func (r *ResourceFile) ToCreateDDRequest() (*types.CreateDDRequest, error) {
	if r.Kind != "DataDescriptor" {
		return nil, fmt.Errorf("resource kind is '%s', expected 'DataDescriptor'", r.Kind)
	}

	// Validate required fields
	if r.Spec.Name == "" {
		return nil, fmt.Errorf("spec.name is required")
	}
	if r.Spec.Namespace == "" {
		return nil, fmt.Errorf("spec.namespace is required")
	}
	if r.Spec.DescriptorType == "" {
		return nil, fmt.Errorf("spec.descriptorType is required")
	}
	if len(r.Spec.Sources) == 0 {
		return nil, fmt.Errorf("spec.sources is required and must not be empty")
	}

	return &types.CreateDDRequest{
		Name:           r.Spec.Name,
		Namespace:      r.Spec.Namespace,
		Labels:         r.Spec.Labels,
		DescriptorType: r.Spec.DescriptorType,
		Sources:        r.Spec.Sources,
	}, nil
}
