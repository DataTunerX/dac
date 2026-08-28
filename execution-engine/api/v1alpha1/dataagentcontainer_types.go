/*
Copyright 2025.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// DataPolicy defines how data sources should be selected
type DataPolicy struct {
	// Selector for data sources by name
	DataSourceType     string   `json:"dataSourceType,omitempty"`
	SemanticGroupID    string   `json:"semanticGroupID,omitempty"`
	SourceNameSelector []string `json:"sourceNameSelector,omitempty"`
}

// SkillPolicy binds skill-hub packages. Dedicated skill DACs execute them in a
// skill-agent; ds/normal DACs execute them locally in the orchestrator.
type SkillPolicy struct {
	// Skills is the multi-select list from skill-hub.
	// Constraint: SkillRef.Name must be unique within one DAC (even across namespaces).
	Skills []SkillRef `json:"skills,omitempty"`
}

// SkillRef is a downloadable skill package reference in skill-hub (editable selection).
// Only binding identity: namespace + name + optional version. Description lives in agentCard.skills (from hub detail).
type SkillRef struct {
	// Namespace is the skill-hub namespace (not the K8s namespace). Required; non-default supported.
	Namespace string `json:"namespace"`
	// Name is the skill name (matches zip / SKILL.md name). Required.
	Name string `json:"name"`
	// Version pins a version; empty means always fetch latest.
	Version string `json:"version,omitempty"`
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

// ModelSpec defines the LLM models to use
type ModelSpec struct {
	PlannerLLM string `json:"plannerLLM"`
	ExpertLLM  string `json:"expertLLM"`
}

// DataAgentContainerSpec defines the desired state of DataAgentContainer
type DataAgentContainerSpec struct {
	DataPolicy DataPolicy `json:"dataPolicy"`
	// SkillPolicy is the raw skill-hub selection for dedicated or locally attached skills.
	SkillPolicy               SkillPolicy `json:"skillPolicy,omitempty"`
	AgentCard                 AgentCard   `json:"agentCard"`
	DACType                   string      `json:"dacType"`
	Model                     ModelSpec   `json:"model"`
	OrchestratorAgentMaxLoops string      `json:"orchestratorAgentMaxLoops"`
	ExpertAgentMaxSteps       string      `json:"expertAgentMaxSteps"`
}

// ActiveDataDescriptor tracks which data descriptors are being used
type ActiveDataDescriptor struct {
	Name       string `json:"name"`
	Namespace  string `json:"namespace"`
	LastSynced string `json:"lastSynced"`
}

// Endpoint defines how to connect to the agent
type Endpoint struct {
	Address  string `json:"address"`
	Port     int32  `json:"port"`
	Protocol string `json:"protocol"`
}

// DataAgentContainerStatus defines the observed state of DataAgentContainer
type DataAgentContainerStatus struct {
	ActiveDataDescriptors []ActiveDataDescriptor `json:"activeDataDescriptors,omitempty"`
	Endpoint              Endpoint               `json:"endpoint,omitempty"`
	Conditions            []Condition            `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// DataAgentContainer is the Schema for the dataagentcontainers API.
type DataAgentContainer struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   DataAgentContainerSpec   `json:"spec,omitempty"`
	Status DataAgentContainerStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// DataAgentContainerList contains a list of DataAgentContainer.
type DataAgentContainerList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []DataAgentContainer `json:"items"`
}

func init() {
	SchemeBuilder.Register(&DataAgentContainer{}, &DataAgentContainerList{})
}
