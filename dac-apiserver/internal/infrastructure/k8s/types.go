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
		DescriptorType string          `json:"descriptorType"`
		GPUEnabled     string          `json:"gpuEnabled,omitempty"`
		Sources        []K8sDataSource `json:"sources"`
	} `json:"spec"`
	Status struct {
		SourceStatuses []entity.SourceStatus    `json:"sourceStatuses,omitempty"`
		ConsumedBy     []entity.ObjectReference `json:"consumedBy,omitempty"`
		OverallPhase   string                   `json:"overallPhase,omitempty"`
		Conditions     []entity.Condition       `json:"conditions,omitempty"`
	} `json:"status,omitempty"`
}

// K8sDataSource mirrors the DataDescriptor CRD schema (spec.sources[]).
// NOTE: do NOT reuse `entity.DataSource` here, because entity structs are designed for API/DTO and
// may not match the CRD JSON shape (e.g. prompts.prompts.name LocalObjectReference nesting).
type K8sDataSource struct {
	Type     string            `json:"type"`
	Name     string            `json:"name"`
	Metadata map[string]string `json:"metadata,omitempty"`
	Extract  *struct {
		Tables []string `json:"tables,omitempty"`
		Querys []string `json:"querys,omitempty"`
		Files  []string `json:"files,omitempty"`
	} `json:"extract,omitempty"`
	Prompts *struct {
		Prompts *struct {
			Name string `json:"name,omitempty"`
		} `json:"prompts,omitempty"`
	} `json:"prompts,omitempty"`
	CodeRepo *struct {
		CodeRepoType   string `json:"codeRepoType,omitempty"`
		CodeRepoPath   string `json:"codeRepoPath,omitempty"`
		CodeRepoBranch string `json:"codeRepoBranch,omitempty"`
		CodeRepoToken  string `json:"codeRepoToken,omitempty"`
	} `json:"codeRepo,omitempty"`
	Processing *struct {
		Cleaning []entity.CleaningRule `json:"cleaning,omitempty"`
	} `json:"processing,omitempty"`
	Classification []entity.Classification `json:"classification,omitempty"`
}

// K8sAgentContainer 直接映射 K8s CRD 结构，用于 JSON 序列化/反序列化
type K8sAgentContainer struct {
	APIVersion string            `json:"apiVersion"`
	Kind       string            `json:"kind"`
	Metadata   metav1.ObjectMeta `json:"metadata"`
	Spec       struct {
		DACType    string `json:"dacType,omitempty"`
		DataPolicy struct {
			DataSourceType     string   `json:"dataSourceType,omitempty"`
			SemanticGroupID    string   `json:"semanticGroupID,omitempty"`
			SourceNameSelector []string `json:"sourceNameSelector,omitempty"`
		} `json:"dataPolicy"`
		AgentCard struct {
			Name        string `json:"name"`
			Description string `json:"description"`
			Skills      []struct {
				ID          string   `json:"id"`
				Name        string   `json:"name"`
				Description string   `json:"description"`
				Tags        []string `json:"tags,omitempty"`
				Examples    []string `json:"examples,omitempty"`
			} `json:"skills,omitempty"`
		} `json:"agentCard"`
		Model struct {
			Embedding  string `json:"embedding,omitempty"`
			ExpertLLM  string `json:"expertLLM"`
			PlannerLLM string `json:"plannerLLM"`
		} `json:"model"`
		ExpertAgentMaxSteps       string `json:"expertAgentMaxSteps,omitempty"`
		OrchestratorAgentMaxLoops string `json:"orchestratorAgentMaxLoops,omitempty"`
	} `json:"spec"`
	Status struct {
		ActiveDataDescriptors []struct {
			Name       string `json:"name"`
			Namespace  string `json:"namespace"`
			LastSynced string `json:"lastSynced"`
		} `json:"activeDataDescriptors,omitempty"`
		Endpoint *struct {
			Address  string `json:"address"`
			Port     int32  `json:"port"`
			Protocol string `json:"protocol"`
		} `json:"endpoint,omitempty"`
		Conditions []struct {
			Type               string `json:"type"`
			Status             string `json:"status"`
			LastTransitionTime string `json:"lastTransitionTime,omitempty"`
			Reason             string `json:"reason,omitempty"`
			Message            string `json:"message,omitempty"`
		} `json:"conditions,omitempty"`
	} `json:"status,omitempty"`
}
