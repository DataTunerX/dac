package k8s

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// K8sDataDescriptor 直接映射 K8s CRD 结构，用于 JSON 序列化/反序列化
type K8sDataDescriptor struct {
	APIVersion string            `json:"apiVersion"`
	Kind       string            `json:"kind"`
	Metadata   metav1.ObjectMeta `json:"metadata"`
	Spec       struct {
		DescriptorType string              `json:"descriptorType"`
		Sources        []entity.DataSource `json:"sources"`
	} `json:"spec"`
	Status struct {
		SourceStatuses []entity.SourceStatus    `json:"sourceStatuses,omitempty"`
		ConsumedBy     []entity.ObjectReference `json:"consumedBy,omitempty"`
		OverallPhase   string                   `json:"overallPhase,omitempty"`
		Conditions     []entity.Condition       `json:"conditions,omitempty"`
	} `json:"status,omitempty"`
}

// K8sAgentContainer 直接映射 K8s CRD 结构，用于 JSON 序列化/反序列化
type K8sAgentContainer struct {
	APIVersion string            `json:"apiVersion"`
	Kind       string            `json:"kind"`
	Metadata   metav1.ObjectMeta `json:"metadata"`
	Spec       struct {
		DataPolicy          entity.DataPolicy `json:"dataPolicy"`
		AgentCard           entity.AgentCard  `json:"agentCard"`
		Model               entity.ModelSpec  `json:"model"`
		ExpertAgentMaxSteps string            `json:"expertAgentMaxSteps,omitempty"`
	} `json:"spec"`
	Status struct {
		ActiveDataDescriptors []entity.ActiveDataDescriptor `json:"activeDataDescriptors,omitempty"`
		Endpoint              *entity.Endpoint              `json:"endpoint,omitempty"`
		Conditions            []entity.Condition            `json:"conditions,omitempty"`
	} `json:"status,omitempty"`
}
