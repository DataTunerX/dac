package loader

import (
	"fmt"
	"os"

	"sigs.k8s.io/yaml"

	"github.com/lvyanru/dac-apiserver/internal/cli/types"
)

// Metadata represents standard Kubernetes-style metadata section.
// This allows YAML files that follow the common apiVersion/kind/metadata/spec
// layout to be used directly with dactl.
type Metadata struct {
	Name      string            `yaml:"name,omitempty"`
	Namespace string            `yaml:"namespace,omitempty"`
	Labels    map[string]string `yaml:"labels,omitempty"`
}

// ResourceFile represents a resource definition loaded from a YAML file
type ResourceFile struct {
	// Kind specifies the resource type: "DataAgentContainer" or "DataDescriptor"
	Kind string `yaml:"kind"`
	// Metadata mirrors Kubernetes resource metadata. It is optional but, when
	// present, can be used as a fallback for name/namespace/labels.
	Metadata Metadata `yaml:"metadata,omitempty"`
	// Spec contains the resource specification
	Spec ResourceSpec `yaml:"spec"`
}

// ResourceSpec defines a unified resource specification.
// Note: name/namespace/labels follow Kubernetes conventions and are taken
// from the top-level metadata field instead of spec to avoid inventing a
// custom schema.
type ResourceSpec struct {
	// Fields for DataAgentContainer (DAC)
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

	// Follow Kubernetes conventions: use metadata.name / metadata.namespace
	// instead of custom spec.name/spec.namespace fields.
	name := r.Metadata.Name
	if name == "" {
		return nil, fmt.Errorf("metadata.name is required")
	}

	namespace := r.Metadata.Namespace
	if namespace == "" {
		return nil, fmt.Errorf("metadata.namespace is required")
	}

	// DataPolicy must still be configured under spec to keep semantics clear.
	if r.Spec.DataPolicy == nil || len(r.Spec.DataPolicy.SourceNameSelector) == 0 {
		return nil, fmt.Errorf("spec.dataPolicy.sourceNameSelector is required")
	}

	// Set default values
	agentCard := r.Spec.AgentCard
	if agentCard == nil {
		agentCard = &types.AgentCard{
			Name:        name,
			Description: fmt.Sprintf("Data Agent for %s", name),
			Skills:      []types.AgentSkill{},
		}
	} else if agentCard.Name == "" {
		agentCard.Name = name
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

	// Labels follow Kubernetes conventions and are taken from metadata.labels.
	labels := r.Metadata.Labels

	return &types.CreateDACRequest{
		Name:                name,
		Namespace:           namespace,
		Labels:              labels,
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

	// For DataDescriptor as well, strictly follow Kubernetes-style metadata
	// for identity fields.
	name := r.Metadata.Name
	if name == "" {
		return nil, fmt.Errorf("metadata.name is required")
	}

	namespace := r.Metadata.Namespace
	if namespace == "" {
		return nil, fmt.Errorf("metadata.namespace is required")
	}

	if r.Spec.DescriptorType == "" {
		return nil, fmt.Errorf("spec.descriptorType is required")
	}
	if len(r.Spec.Sources) == 0 {
		return nil, fmt.Errorf("spec.sources is required and must not be empty")
	}

	labels := r.Metadata.Labels

	return &types.CreateDDRequest{
		Name:           name,
		Namespace:      namespace,
		Labels:         labels,
		DescriptorType: r.Spec.DescriptorType,
		Sources:        r.Spec.Sources,
	}, nil
}
