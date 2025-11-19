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

// DataSourceType defines the type of data source
type DataSourceType string

const (
	DataSourceMySQL      DataSourceType = "mysql"
	DataSourceMinIO      DataSourceType = "minio"
	DataSourcePostgres   DataSourceType = "postgres"
	DataSourceFileServer DataSourceType = "fileserver"
)

// DataSource defines a data source configuration
type DataSource struct {
	Type           DataSourceType    `json:"type"`
	Name           string            `json:"name"`
	Metadata       map[string]string `json:"metadata,omitempty"`
	Extract        *ExtractConfig    `json:"extract,omitempty"`
	Prompts        *Prompts          `json:"prompts,omitempty"`
	Processing     ProcessingConfig  `json:"processing,omitempty"`
	Classification []Classification  `json:"classification,omitempty"`
}

// ExtractConfig defines extraction configuration for data sources
type ExtractConfig struct {
	Tables []string `json:"tables,omitempty"`
	Querys []string `json:"querys,omitempty"`
	Files  []string `json:"files,omitempty"`
}

// Prompts defines fewshots and background_knowledge for data sources
type Prompts struct {
	Prompts LocalObjectReference `json:"prompts,omitempty"`
}

type ConfigMapData struct {
	FewShots            []FewShot             `json:"fewshots"`
	BackgroundKnowledge []BackgroundKnowledge `json:"background_knowledge"`
}

type FewShot struct {
	Query  string `json:"query"`
	Answer string `json:"answer"`
}

type BackgroundKnowledge struct {
	Description string `json:"description"`
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

// LocalObjectReference contains enough information to let you locate the referenced object inside the same namespace.
type LocalObjectReference struct {
	Name string `json:"name"`
}

// SourceStatus defines the status of a data source
type SourceStatus struct {
	Name         string      `json:"name,omitempty"`
	Phase        string      `json:"phase,omitempty"`
	LastSyncTime metav1.Time `json:"lastSyncTime,omitempty"`
	Records      int64       `json:"records,omitempty"`
	TaskID       string      `json:"taskID,omitempty"`
}

// DataDescriptorSpec defines the desired state of DataDescriptor.
type DataDescriptorSpec struct {
	// INSERT ADDITIONAL SPEC FIELDS - desired state of cluster
	// Important: Run "make" to regenerate code after modifying this file
	DescriptorType string       `json:"descriptorType,omitempty"`
	Sources        []DataSource `json:"sources,omitempty"`
}

// DataDescriptorStatus defines the observed state of DataDescriptor.
type DataDescriptorStatus struct {
	// INSERT ADDITIONAL STATUS FIELD - define observed state of cluster
	// Important: Run "make" to regenerate code after modifying this file
	SourceStatuses []SourceStatus         `json:"sourceStatuses,omitempty"`
	ConsumedBy     []LocalObjectReference `json:"consumedBy,omitempty"`
	OverallPhase   string                 `json:"overallPhase,omitempty"`
	Conditions     []Condition            `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// DataDescriptor is the Schema for the datadescriptors API.
type DataDescriptor struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   DataDescriptorSpec   `json:"spec,omitempty"`
	Status DataDescriptorStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// DataDescriptorList contains a list of DataDescriptor.
type DataDescriptorList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []DataDescriptor `json:"items"`
}

func init() {
	SchemeBuilder.Register(&DataDescriptor{}, &DataDescriptorList{})
}
