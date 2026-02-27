package generator

import (
	"context"
	"encoding/json"
	"fmt"
	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
	"github.com/DataTunerX/dac/execution-engine/client/k8s"
	"github.com/go-logr/logr"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"strings"
)

// DataAgentContainerHandler handles the reconciliation logic for DataAgentContainer resources.
type DataAgentContainerGenerator struct {
	K8sServices k8s.Services
	Kubeclient  client.Client
	Logger      logr.Logger
}

// LLMConfig
type LLMConfig struct {
	Provider string
	APIKey   string
	BaseURL  string
	Model    string
}

// DACConfig
type DACConfig struct {
	ObservationBaseURL           string
	ObservationSecretKey         string
	ObservationPublicKey         string
	RedisHost                    string
	RedisPort                    string
	RedisPassword                string
	DataServicesURL              string
	DSExpertAgentRegistry        string
	BIZExpertAgentRegistry       string
	DSOrchestratorAgentRegistry  string
	BIZOrchestratorAgentRegistry string
	OrchestratorAgentImage       string
	ExpertAgentImage             string
	DataSinkerImage              string
	DSDataServicesImage          string
	CodeAgentImage               string
	DocAgentImage                string
}

func (h *DataAgentContainerGenerator) Do(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) error {
	logger := h.Logger.WithValues("namespace", dac.Namespace, "name", dac.Name)
	logger.Info("Generate DataAgentContainer K8S resources")

	labels := map[string]string{
		"app": dac.Name,
	}

	isController := true
	ownerRefs := []metav1.OwnerReference{
		{
			APIVersion: dac.APIVersion,
			Kind:       dac.Kind,
			Name:       dac.Name,
			UID:        dac.UID,
			Controller: &isController,
		},
	}

	service := h.GenerateDataAgentContainerService(dac, labels, ownerRefs)
	serviceName := h.GenerateDataAgentContainerServiceName(dac)
	if _, err := h.K8sServices.GetService(dac.Namespace, serviceName); err != nil {
		if !errors.IsNotFound(err) {
			return err
		}
		err := h.K8sServices.CreateService(dac.Namespace, service)
		if err != nil {
			return err
		}
	}

	if dac.Spec.DACType == "ds" {
		deployment, err := h.GenerateDSDataAgentContainerDeployment(ctx, dac, labels, ownerRefs)
		if err != nil {
			return err
		}

		deploymentName := h.GenerateDataAgentContainerDeploymentName(dac)
		if _, err := h.K8sServices.GetDeployment(dac.Namespace, deploymentName); err != nil {
			if !errors.IsNotFound(err) {
				return err
			}
			err = h.K8sServices.CreateDeployment(dac.Namespace, deployment)
			if err != nil {
				return err
			}
		}
	}

	if dac.Spec.DACType == "normal" {
		deployment, err := h.GenerateDataAgentContainerDeployment(ctx, dac, labels, ownerRefs)
		if err != nil {
			return err
		}

		deploymentName := h.GenerateDataAgentContainerDeploymentName(dac)
		if _, err := h.K8sServices.GetDeployment(dac.Namespace, deploymentName); err != nil {
			if !errors.IsNotFound(err) {
				return err
			}
			err = h.K8sServices.CreateDeployment(dac.Namespace, deployment)
			if err != nil {
				return err
			}
		}
	}

	return nil
}

func (h *DataAgentContainerGenerator) GenerateDataAgentContainerService(dac *dacv1alpha1.DataAgentContainer, labels map[string]string, ownerRefs []metav1.OwnerReference) *corev1.Service {
	serviceName := h.GenerateDataAgentContainerServiceName(dac)
	orchestratorTargetPort := intstr.FromInt(10100)
	expertTargetPort := intstr.FromInt(10101)
	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:            serviceName,
			Namespace:       dac.Namespace,
			Labels:          labels,
			OwnerReferences: ownerRefs,
		},
		Spec: corev1.ServiceSpec{
			Type: corev1.ServiceTypeClusterIP,
			Ports: []corev1.ServicePort{
				{
					Port:       10100,
					Protocol:   corev1.ProtocolTCP,
					Name:       "orchestrator",
					TargetPort: orchestratorTargetPort,
				},
				{
					Port:       10101,
					Protocol:   corev1.ProtocolTCP,
					Name:       "expert",
					TargetPort: expertTargetPort,
				},
			},
			Selector: labels,
		},
	}
}

// DataAgentContainerResourceName 返回 DAC 相关 K8s 资源的统一名称，加 dac- 前缀以与 DD 资源区分
func DataAgentContainerResourceName(dac *dacv1alpha1.DataAgentContainer) string {
	return "dac-" + dac.Name
}

func (h *DataAgentContainerGenerator) GenerateDataAgentContainerServiceName(dac *dacv1alpha1.DataAgentContainer) string {
	return DataAgentContainerResourceName(dac)
}

func (h *DataAgentContainerGenerator) generateExpertAgentEnvs(dac *dacv1alpha1.DataAgentContainer, serviceName string, ddDescriptorTypes string, dacConfig *DACConfig) []corev1.EnvVar {
	envs := []corev1.EnvVar{}

	agentCardURL := serviceName + "." + dac.Namespace + ".svc.cluster.local"

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Host",
		Value: agentCardURL,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Port",
		Value: "10101",
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Name",
		Value: dac.Spec.AgentCard.Name,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Description",
		Value: dac.Spec.AgentCard.Description,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "DataSourceType",
		Value: dac.Spec.DataPolicy.DataSourceType,
	})

	if dac.Spec.DACType == "ds" {
		dataServicesURL := "http://localhost:8000"
		envs = append(envs, corev1.EnvVar{
			Name:  "DataServicesURL",
			Value: dataServicesURL,
		})

		agentRegistry := ""
		if dacConfig != nil {
			agentRegistry = dacConfig.DSExpertAgentRegistry
		} else {
			agentRegistry = "http://expert-registry.dac.svc.cluster.local:8000"
		}

		envs = append(envs, corev1.EnvVar{
			Name:  "AgentRegistry",
			Value: agentRegistry,
		})
		leafAgentRegistry := ""
		if dacConfig != nil {
			leafAgentRegistry = dacConfig.DSOrchestratorAgentRegistry
		} else {
			leafAgentRegistry = "http://orchestrator-registry.dac.svc.cluster.local:8000"
		}
		envs = append(envs, corev1.EnvVar{
			Name:  "LeafAgentRegistry",
			Value: leafAgentRegistry,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "DD_NAMESPACE",
			Value: dac.Namespace,
		})

		dataDescriptor := strings.Join(dac.Spec.DataPolicy.SourceNameSelector, ",")
		envs = append(envs, corev1.EnvVar{
			Name:  "Data_Descriptor",
			Value: dataDescriptor,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "DescriptorTypes",
			Value: ddDescriptorTypes,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "Enable_History",
			Value: "disable",
		})
	}

	if dac.Spec.DACType == "normal" {
		envs = append(envs, corev1.EnvVar{
			Name:  "SemanticGroupID",
			Value: dac.Spec.DataPolicy.SemanticGroupID,
		})

		agentRegistry := ""
		if dacConfig != nil {
			agentRegistry = dacConfig.BIZExpertAgentRegistry
		} else {
			agentRegistry = "http://biz-expert-registry.dac.svc.cluster.local:8000"
		}

		envs = append(envs, corev1.EnvVar{
			Name:  "AgentRegistry",
			Value: agentRegistry,
		})
		leafAgentRegistry := ""
		if dacConfig != nil {
			leafAgentRegistry = dacConfig.DSOrchestratorAgentRegistry
		} else {
			leafAgentRegistry = "http://orchestrator-registry.dac.svc.cluster.local:8000"
		}
		envs = append(envs, corev1.EnvVar{
			Name:  "LeafAgentRegistry",
			Value: leafAgentRegistry,
		})

		dataServicesURL := "http://data-services.dac.svc.cluster.local:8000"
		envs = append(envs, corev1.EnvVar{
			Name:  "DataServicesURL",
			Value: dataServicesURL,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "Enable_History",
			Value: "enable",
		})
	}

	if dacConfig != nil {
		envs = append(envs, corev1.EnvVar{
			Name:  "LANGFUSE_BASE_URL",
			Value: dacConfig.ObservationBaseURL,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "LANGFUSE_SECRET_KEY",
			Value: dacConfig.ObservationSecretKey,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "LANGFUSE_PUBLIC_KEY",
			Value: dacConfig.ObservationPublicKey,
		})
	}

	return envs
}

func (h *DataAgentContainerGenerator) generateOrchestratorAgentEnvs(dac *dacv1alpha1.DataAgentContainer, serviceName string, ddDescriptorTypes string, dacConfig *DACConfig) []corev1.EnvVar {
	envs := []corev1.EnvVar{}

	agentCardURL := serviceName + "." + dac.Namespace + ".svc.cluster.local"

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Host",
		Value: agentCardURL,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Port",
		Value: "10100",
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Name",
		Value: dac.Spec.AgentCard.Name,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Description",
		Value: dac.Spec.AgentCard.Description,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "DataSourceType",
		Value: dac.Spec.DataPolicy.DataSourceType,
	})

	if dac.Spec.DACType == "ds" {
		dataServicesURL := "http://localhost:8000"
		envs = append(envs, corev1.EnvVar{
			Name:  "DataServicesURL",
			Value: dataServicesURL,
		})

		agentRegistry := ""
		if dacConfig != nil {
			agentRegistry = dacConfig.DSOrchestratorAgentRegistry
		} else {
			agentRegistry = "http://orchestrator-registry.dac.svc.cluster.local:8000"
		}

		envs = append(envs, corev1.EnvVar{
			Name:  "AgentRegistry",
			Value: agentRegistry,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "DD_NAMESPACE",
			Value: dac.Namespace,
		})

		dataDescriptor := strings.Join(dac.Spec.DataPolicy.SourceNameSelector, ",")
		envs = append(envs, corev1.EnvVar{
			Name:  "Data_Descriptor",
			Value: dataDescriptor,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "DescriptorTypes",
			Value: ddDescriptorTypes,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "Enable_History",
			Value: "disable",
		})
	}

	if dac.Spec.DACType == "normal" {
		envs = append(envs, corev1.EnvVar{
			Name:  "SemanticGroupID",
			Value: dac.Spec.DataPolicy.SemanticGroupID,
		})

		agentRegistry := ""
		if dacConfig != nil {
			agentRegistry = dacConfig.BIZOrchestratorAgentRegistry
		} else {
			agentRegistry = "http://biz-orchestrator-registry.dac.svc.cluster.local:8000"
		}

		envs = append(envs, corev1.EnvVar{
			Name:  "AgentRegistry",
			Value: agentRegistry,
		})

		dataServicesURL := "http://data-services.dac.svc.cluster.local:8000"
		envs = append(envs, corev1.EnvVar{
			Name:  "DataServicesURL",
			Value: dataServicesURL,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "Enable_History",
			Value: "enable",
		})
	}

	if dacConfig != nil {
		envs = append(envs, corev1.EnvVar{
			Name:  "LANGFUSE_BASE_URL",
			Value: dacConfig.ObservationBaseURL,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "LANGFUSE_SECRET_KEY",
			Value: dacConfig.ObservationSecretKey,
		})

		envs = append(envs, corev1.EnvVar{
			Name:  "LANGFUSE_PUBLIC_KEY",
			Value: dacConfig.ObservationPublicKey,
		})
	}

	return envs
}

func (h *DataAgentContainerGenerator) createConfigMapForSkills(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) error {
	if dac.Spec.AgentCard.Skills != nil {
		skillsJSON, err := json.Marshal(dac.Spec.AgentCard.Skills)
		if err != nil {
			return err
		}

		configMap := &corev1.ConfigMap{
			ObjectMeta: metav1.ObjectMeta{
				Name:      DataAgentContainerResourceName(dac),
				Namespace: dac.Namespace,
				OwnerReferences: []metav1.OwnerReference{
					*metav1.NewControllerRef(dac, dacv1alpha1.GroupVersion.WithKind("DataAgentContainer")),
				},
			},
			Data: map[string]string{
				"skills.json": string(skillsJSON),
			},
		}

		return h.K8sServices.CreateIfNotExistsConfigMap(dac.Namespace, configMap)
	}
	return nil
}

// getObserveConfig get data from configmap
func (h *DataAgentContainerGenerator) getDACConfig(ctx context.Context) (*DACConfig, error) {
	configMap := &corev1.ConfigMap{}

	configMapName := "dac-configuration"

	configMapNameSpace := "dac"

	err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: configMapName, Namespace: configMapNameSpace}, configMap)
	if err != nil {
		if errors.IsNotFound(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get ConfigMap: %v", err)
	}

	return &DACConfig{
		ObservationBaseURL:           configMap.Data["observation-base-url"],
		ObservationSecretKey:         configMap.Data["observation-secret-key"],
		ObservationPublicKey:         configMap.Data["observation-public-key"],
		RedisHost:                    configMap.Data["redis-host"],
		RedisPort:                    configMap.Data["redis-port"],
		RedisPassword:                configMap.Data["redis-password"],
		DataServicesURL:              configMap.Data["data-services-url"],
		BIZExpertAgentRegistry:       configMap.Data["biz-expert-agent-registry"],
		DSExpertAgentRegistry:        configMap.Data["expert-agent-registry"],
		BIZOrchestratorAgentRegistry: configMap.Data["biz-orchestrator-agent-registry"],
		DSOrchestratorAgentRegistry:  configMap.Data["orchestrator-agent-registry"],
		OrchestratorAgentImage:       configMap.Data["orchestrator-agent-image"],
		ExpertAgentImage:             configMap.Data["expert-agent-image"],
		DataSinkerImage:              configMap.Data["data-sinker-image"],
		DSDataServicesImage:          configMap.Data["ds-data-services-image"],
		CodeAgentImage:               configMap.Data["code-agent-image"],
		DocAgentImage:                configMap.Data["doc-agent-image"],
	}, nil
}

// getPlannerLLMConfig get data from configmap
func (h *DataAgentContainerGenerator) getPlannerLLMConfig(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) (*LLMConfig, error) {
	configMap := &corev1.ConfigMap{}

	err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: dac.Spec.Model.PlannerLLM, Namespace: dac.Namespace}, configMap)
	if err != nil {
		return nil, fmt.Errorf("failed to get ConfigMap: %v", err)
	}

	return &LLMConfig{
		Provider: configMap.Data["provider"],
		APIKey:   configMap.Data["api-key"],
		BaseURL:  configMap.Data["base-url"],
		Model:    configMap.Data["model"],
	}, nil
}

// getExpertLLMConfig get data from configmap
func (h *DataAgentContainerGenerator) getExpertLLMConfig(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) (*LLMConfig, error) {
	configMap := &corev1.ConfigMap{}

	err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: dac.Spec.Model.ExpertLLM, Namespace: dac.Namespace}, configMap)
	if err != nil {
		return nil, fmt.Errorf("failed to get ConfigMap: %v", err)
	}

	return &LLMConfig{
		Provider: configMap.Data["provider"],
		APIKey:   configMap.Data["api-key"],
		BaseURL:  configMap.Data["base-url"],
		Model:    configMap.Data["model"],
	}, nil
}

// SourceConfig is the unified JSON config for all descriptor types (code, structured-xxx).
// Each DD referenced by a DAC produces one entry; the whole list is marshalled to JSON
// and passed as the DescriptorTypes env var to orchestrator / expert containers.
type SourceConfig struct {
	Name           string            `json:"name"`
	Namespace      string            `json:"namespace,omitempty"`
	DescriptorType string            `json:"descriptorType"`
	DbType         string            `json:"dbType,omitempty"`
	Config         map[string]string `json:"config,omitempty"`
	CodeRepoType   string            `json:"codeRepoType,omitempty"`
	CodeRepoPath   string            `json:"codeRepoPath,omitempty"`
	CodeRepoBranch string            `json:"codeRepoBranch,omitempty"`
	CodeRepoToken  string            `json:"codeRepoToken,omitempty"`
}

// isCodeTypeDD 检查 DataAgentContainer 关联的 DataDescriptor 是否为 code 类型
func (h *DataAgentContainerGenerator) isCodeTypeDD(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) (bool, error) {
	for _, item := range dac.Spec.DataPolicy.SourceNameSelector {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}

		dataDescriptor := &dacv1alpha1.DataDescriptor{}
		err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: item, Namespace: dac.Namespace}, dataDescriptor)
		if err != nil {
			return false, fmt.Errorf("failed to get DataDescriptor %s: %v", item, err)
		}

		if dataDescriptor.Spec.DescriptorType == "code" {
			return true, nil
		}
	}
	return false, nil
}

// isUnstructuredTypeDD checks whether any DataDescriptor referenced by the DAC is of unstructured type.
func (h *DataAgentContainerGenerator) isUnstructuredTypeDD(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) (bool, error) {
	for _, item := range dac.Spec.DataPolicy.SourceNameSelector {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}

		dataDescriptor := &dacv1alpha1.DataDescriptor{}
		err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: item, Namespace: dac.Namespace}, dataDescriptor)
		if err != nil {
			return false, fmt.Errorf("failed to get DataDescriptor %s: %v", item, err)
		}

		if dataDescriptor.Spec.DescriptorType == "unstructured" {
			return true, nil
		}
	}
	return false, nil
}

// getDDSourceConfigJson builds a unified JSON array of SourceConfig for every
// DataDescriptor referenced by the DAC.  The output is set as the DescriptorTypes
// env var for orchestrator / expert containers.
func (h *DataAgentContainerGenerator) getDDSourceConfigJson(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) (string, error) {
	var configs []SourceConfig

	for _, item := range dac.Spec.DataPolicy.SourceNameSelector {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}

		dd := &dacv1alpha1.DataDescriptor{}
		if err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: item, Namespace: dac.Namespace}, dd); err != nil {
			return "", fmt.Errorf("failed to get DataDescriptor %s: %v", item, err)
		}

		cfg := SourceConfig{
			Name:           item,
			Namespace:      dac.Namespace,
			DescriptorType: dd.Spec.DescriptorType,
		}

		dt := strings.ToLower(dd.Spec.DescriptorType)

		if dt == "code" {
			// Code type: populate code-repo fields
			if len(dd.Spec.Sources) > 0 && dd.Spec.Sources[0].CodeRepo != nil {
				repo := dd.Spec.Sources[0].CodeRepo
				cfg.CodeRepoType = repo.CodeRepoType
				cfg.CodeRepoPath = repo.CodeRepoPath
				cfg.CodeRepoBranch = repo.CodeRepoBranch
				cfg.CodeRepoToken = repo.CodeRepoToken
			}
			if cfg.CodeRepoPath == "" && len(dd.Spec.Sources) > 0 {
				src := dd.Spec.Sources[0]
				if len(src.Metadata) > 0 {
					if v, ok := src.Metadata["codeRepoPath"]; ok {
						cfg.CodeRepoPath = v
					}
					if v, ok := src.Metadata["codeRepoBranch"]; ok {
						cfg.CodeRepoBranch = v
					}
					if v, ok := src.Metadata["codeRepoToken"]; ok {
						cfg.CodeRepoToken = v
					}
					if cfg.CodeRepoType == "" && src.Type != "" {
						cfg.CodeRepoType = string(src.Type)
					}
				}
			}
		} else if strings.HasPrefix(dt, "structured") {
			// Structured type (structured-mysql, structured-postgres, …):
			// extract the db sub-type and copy source metadata into config.
			parts := strings.SplitN(dt, "-", 2)
			if len(parts) == 2 {
				cfg.DbType = parts[1]
			}
			if len(dd.Spec.Sources) > 0 && len(dd.Spec.Sources[0].Metadata) > 0 {
				configMap := make(map[string]string)
				for k, v := range dd.Spec.Sources[0].Metadata {
					configMap[k] = v
				}
				cfg.Config = configMap
			}
		} else if dt == "unstructured" {
			// Unstructured type: carry source metadata + source type into config.
			if len(dd.Spec.Sources) > 0 {
				configMap := make(map[string]string)
				for k, v := range dd.Spec.Sources[0].Metadata {
					configMap[k] = v
				}
				if dd.Spec.Sources[0].Type != "" {
					configMap["type"] = string(dd.Spec.Sources[0].Type)
				}
				cfg.Config = configMap
			}
		} else {
			// Any other future type: just carry metadata through
			if len(dd.Spec.Sources) > 0 && len(dd.Spec.Sources[0].Metadata) > 0 {
				configMap := make(map[string]string)
				for k, v := range dd.Spec.Sources[0].Metadata {
					configMap[k] = v
				}
				cfg.Config = configMap
			}
		}

		configs = append(configs, cfg)
	}

	if len(configs) == 0 {
		return "[]", nil
	}

	jsonBytes, err := json.Marshal(configs)
	if err != nil {
		return "", fmt.Errorf("failed to marshal source configs to JSON: %v", err)
	}
	return string(jsonBytes), nil
}

func (h *DataAgentContainerGenerator) generateOrchestratorAgentArgs(dac *dacv1alpha1.DataAgentContainer, llmConfig *LLMConfig, dacConfig *DACConfig) []string {
	port := "10100"

	redisHost := ""

	if dacConfig != nil {
		redisHost = dacConfig.RedisHost
	} else {
		redisHost = "redis-server.dac.svc.cluster.local"
	}

	redisPort := ""

	if dacConfig != nil {
		redisPort = dacConfig.RedisPort
	} else {
		redisPort = "6379"
	}

	redisPassword := ""

	if dacConfig != nil {
		redisPassword = dacConfig.RedisPassword
	} else {
		redisPassword = "123"
	}

	redisDB := "0"

	if dac.Spec.DACType == "ds" {
		redisDB = "0"
	}

	if dac.Spec.DACType == "normal" {
		redisDB = "2"
	}

	cmds := []string{
		"--port",
		port,
		"--redis-host",
		redisHost,
		"--redis-port",
		redisPort,
		"--redis-db",
		redisDB,
		"--password",
		redisPassword,
		"--provider",
		llmConfig.Provider,
		"--api-key",
		llmConfig.APIKey,
		"--base-url",
		llmConfig.BaseURL,
		"--model",
		llmConfig.Model,
		"--max-loops",
		dac.Spec.OrchestratorAgentMaxLoops,
	}
	return cmds
}

func (h *DataAgentContainerGenerator) generateExpertAgentArgs(dac *dacv1alpha1.DataAgentContainer, llmConfig *LLMConfig, dacConfig *DACConfig) []string {
	port := "10101"

	redisHost := ""

	if dacConfig != nil {
		redisHost = dacConfig.RedisHost
	} else {
		redisHost = "redis-server.dac.svc.cluster.local"
	}

	redisPort := ""

	if dacConfig != nil {
		redisPort = dacConfig.RedisPort
	} else {
		redisPort = "6379"
	}

	redisPassword := ""

	if dacConfig != nil {
		redisPassword = dacConfig.RedisPassword
	} else {
		redisPassword = "123"
	}

	redisDB := "1"

	if dac.Spec.DACType == "ds" {
		redisDB = "1"
	}

	if dac.Spec.DACType == "normal" {
		redisDB = "3"
	}

	cmds := []string{
		"--port",
		port,
		"--redis-host",
		redisHost,
		"--redis-port",
		redisPort,
		"--redis-db",
		redisDB,
		"--password",
		redisPassword,
		"--provider",
		llmConfig.Provider,
		"--api-key",
		llmConfig.APIKey,
		"--base-url",
		llmConfig.BaseURL,
		"--model",
		llmConfig.Model,
		"--max-steps",
		dac.Spec.ExpertAgentMaxSteps,
	}
	return cmds
}

func (h *DataAgentContainerGenerator) generateDataServicesEnvs(dac *dacv1alpha1.DataAgentContainer, dacConfig *DACConfig) ([]corev1.EnvVar, error) {
	envs := []corev1.EnvVar{}

	dataServicesURL := ""
	if dacConfig != nil && dacConfig.DataServicesURL != "" {
		dataServicesURL = dacConfig.DataServicesURL
	} else {
		dataServicesURL = "http://data-services.dac.svc.cluster.local:8000"
	}

	envs = append(envs, corev1.EnvVar{
		Name:  "DATA_SERVICES",
		Value: dataServicesURL,
	})

	ddName := ""
	if len(dac.Spec.DataPolicy.SourceNameSelector) > 0 {
		ddName = dac.Spec.DataPolicy.SourceNameSelector[0]
	}

	dataDescriptor := dac.Namespace + "_" + ddName
	dataDescriptor = strings.ReplaceAll(dataDescriptor, "-", "_")

	envs = append(envs, corev1.EnvVar{
		Name:  "DATA_DESCRIPTOR",
		Value: dataDescriptor,
	})

	return envs, nil
}

func (h *DataAgentContainerGenerator) generateDataSinkerEnvs(dac *dacv1alpha1.DataAgentContainer, llmConfig *LLMConfig, dacConfig *DACConfig) ([]corev1.EnvVar, error) {
	envs := []corev1.EnvVar{}

	dataServicesURL := "http://localhost:8000"

	envs = append(envs, corev1.EnvVar{
		Name:  "DATA_SERVICES",
		Value: dataServicesURL,
	})

	ddName := ""
	if len(dac.Spec.DataPolicy.SourceNameSelector) > 0 {
		ddName = dac.Spec.DataPolicy.SourceNameSelector[0]
	}

	dataDescriptor := dac.Namespace + "_" + ddName
	dataDescriptor = strings.ReplaceAll(dataDescriptor, "-", "_")

	envs = append(envs, corev1.EnvVar{
		Name:  "DATA_DESCRIPTOR",
		Value: dataDescriptor,
	})

	if llmConfig != nil {
		if llmConfig.Provider != "" {
			envs = append(envs, corev1.EnvVar{
				Name:  "PROVIDER",
				Value: llmConfig.Provider,
			})
		}
		if llmConfig.APIKey != "" {
			envs = append(envs, corev1.EnvVar{
				Name:  "API_KEY",
				Value: llmConfig.APIKey,
			})
		}
		if llmConfig.BaseURL != "" {
			envs = append(envs, corev1.EnvVar{
				Name:  "BASE_URL",
				Value: llmConfig.BaseURL,
			})
		}
		if llmConfig.Model != "" {
			envs = append(envs, corev1.EnvVar{
				Name:  "Model",
				Value: llmConfig.Model,
			})
		}
	}

	envs = append(envs, corev1.EnvVar{
		Name:  "Temperature",
		Value: "0.01",
	})
	envs = append(envs, corev1.EnvVar{
		Name:  "ENABLE_ALLINONE",
		Value: "disable",
	})
	envs = append(envs, corev1.EnvVar{
		Name:  "SQL_BATCHSIZE",
		Value: "2",
	})
	envs = append(envs, corev1.EnvVar{
		Name:  "SQL_PROCESS_MODE",
		Value: "dictionary",
	})
	envs = append(envs, corev1.EnvVar{
		Name:  "ENABLE_SAMPLE_DATA",
		Value: "enable",
	})
	envs = append(envs, corev1.EnvVar{
		Name:  "MINERU_MODEL_SOURCE",
		Value: "local",
	})
	envs = append(envs, corev1.EnvVar{
		Name:  "MINERU_DEVICE_MODE",
		Value: "cpu",
	})
	envs = append(envs, corev1.EnvVar{
		Name:  "regroup_batch_size",
		Value: "10",
	})

	return envs, nil
}

func (h *DataAgentContainerGenerator) GenerateDataAgentContainerDeploymentName(dac *dacv1alpha1.DataAgentContainer) string {
	return DataAgentContainerResourceName(dac)
}

func (h *DataAgentContainerGenerator) GenerateDSDataAgentContainerDeployment(ctx context.Context, dac *dacv1alpha1.DataAgentContainer, labels map[string]string, ownerRefs []metav1.OwnerReference) (*appsv1.Deployment, error) {

	name := h.GenerateDataAgentContainerDeploymentName(dac)

	serviceName := h.GenerateDataAgentContainerServiceName(dac)

	replicas := int32(1)

	if dac.Spec.AgentCard.Skills != nil {
		err := h.createConfigMapForSkills(ctx, dac)
		if err != nil {
			return nil, err
		}
	}

	dacConfig, err := h.getDACConfig(ctx)
	if err != nil {
		return nil, err
	}

	// Default images for DS type; override from dacConfig only when non-empty
	dataSinkerImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers:v0.6.0-amd64"
	dataServicesImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/dac-data-services:v0.6.0-amd64"
	orchestratorAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/ds-orchestrator-agent:v0.6.0-amd64"
	expertAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/ds-expert-agent:v0.6.0-amd64"
	codeAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/code-agent:v0.6.0-amd64"
	docAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/doc-agent:v0.6.0-amd64"

	if dacConfig != nil {
		if dacConfig.DataSinkerImage != "" {
			dataSinkerImage = dacConfig.DataSinkerImage
		}
		if dacConfig.DSDataServicesImage != "" {
			dataServicesImage = dacConfig.DSDataServicesImage
		}
		if dacConfig.OrchestratorAgentImage != "" {
			orchestratorAgentImage = dacConfig.OrchestratorAgentImage
		}
		if dacConfig.ExpertAgentImage != "" {
			expertAgentImage = dacConfig.ExpertAgentImage
		}
		if dacConfig.CodeAgentImage != "" {
			codeAgentImage = dacConfig.CodeAgentImage
		}
		if dacConfig.DocAgentImage != "" {
			docAgentImage = dacConfig.DocAgentImage
		}
	}

	h.Logger.WithValues("dataSinkerImage", dataSinkerImage).Info("use this image to handler data")

	plannerLLMConfig, err := h.getPlannerLLMConfig(ctx, dac)
	if err != nil {
		return nil, err
	}

	expertLLMConfig, err := h.getExpertLLMConfig(ctx, dac)
	if err != nil {
		return nil, err
	}

	orchestratorAgentArgs := h.generateOrchestratorAgentArgs(dac, plannerLLMConfig, dacConfig)

	expertAgentArgs := h.generateExpertAgentArgs(dac, expertLLMConfig, dacConfig)

	ddDescriptorTypes, err := h.getDDSourceConfigJson(ctx, dac)
	if err != nil {
		return nil, err
	}

	// 判断 expert 容器使用的镜像：code 类型用 code-agent，unstructured 类型用 doc-agent，否则用 ds-expert-agent
	isCodeType, err := h.isCodeTypeDD(ctx, dac)
	if err != nil {
		return nil, err
	}
	isUnstructuredType, err := h.isUnstructuredTypeDD(ctx, dac)
	if err != nil {
		return nil, err
	}

	actualExpertImage := expertAgentImage
	if isCodeType {
		actualExpertImage = codeAgentImage
		h.Logger.Info("Using code-agent image for expert container", "image", codeAgentImage)
	} else if isUnstructuredType {
		actualExpertImage = docAgentImage
		h.Logger.Info("Using doc-agent image for expert container", "image", docAgentImage)
	}

	// dataSinkerEnvs, err := h.generateDataSinkerEnvs(dac, expertLLMConfig, dacConfig)
	// if err != nil {
	// 	return nil, err
	// }

	dataServicesEnvs, err := h.generateDataServicesEnvs(dac, dacConfig)
	if err != nil {
		return nil, err
	}

	podSpec := corev1.PodSpec{
		// ImagePullSecrets: imagePullSecrets,
		Containers: []corev1.Container{
			{
				Name:            "orchestrator",
				Image:           orchestratorAgentImage,
				ImagePullPolicy: corev1.PullIfNotPresent,
				Args:            orchestratorAgentArgs,
				Ports: []corev1.ContainerPort{
					{
						Name:          "orchestrator",
						ContainerPort: 10100,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateOrchestratorAgentEnvs(dac, serviceName, ddDescriptorTypes, dacConfig),
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("2000m"),
						corev1.ResourceMemory: resource.MustParse("8000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("1000Mi"),
					},
				},
			},
			{
				Name:            "expert",
				Image:           actualExpertImage,
				ImagePullPolicy: corev1.PullIfNotPresent,
				Args:            expertAgentArgs,
				Ports: []corev1.ContainerPort{
					{
						Name:          "expert",
						ContainerPort: 10101,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateExpertAgentEnvs(dac, serviceName, ddDescriptorTypes, dacConfig),
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("2000m"),
						corev1.ResourceMemory: resource.MustParse("8000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("1000Mi"),
					},
				},
			},
			{
				Name:            "data-services",
				Image:           dataServicesImage,
				ImagePullPolicy: corev1.PullIfNotPresent,
				Ports: []corev1.ContainerPort{
					{
						Name:          "data-services",
						ContainerPort: 8000,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: dataServicesEnvs,
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("1000m"),
						corev1.ResourceMemory: resource.MustParse("2000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("500Mi"),
					},
				},
			},
			// {
			// 	Name:            "data-sinkers",
			// 	Image:           dataSinkerImage,
			// 	ImagePullPolicy: corev1.PullIfNotPresent,
			// 	Env:             dataSinkerEnvs,
			// 	Resources: corev1.ResourceRequirements{
			// 		Limits: corev1.ResourceList{
			// 			corev1.ResourceCPU:    resource.MustParse("2000m"),
			// 			corev1.ResourceMemory: resource.MustParse("4000Mi"),
			// 		},
			// 		Requests: corev1.ResourceList{
			// 			corev1.ResourceCPU:    resource.MustParse("100m"),
			// 			corev1.ResourceMemory: resource.MustParse("500Mi"),
			// 		},
			// 	},
			// },
		},
	}

	if dac.Spec.AgentCard.Skills != nil {
		skillsConfigMapName := DataAgentContainerResourceName(dac)

		podSpec.Volumes = []corev1.Volume{
			{
				Name: "skills-config",
				VolumeSource: corev1.VolumeSource{
					ConfigMap: &corev1.ConfigMapVolumeSource{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: skillsConfigMapName,
						},
					},
				},
			},
		}

		for i := range podSpec.Containers {
			podSpec.Containers[i].VolumeMounts = []corev1.VolumeMount{
				{
					Name:      "skills-config",
					MountPath: "/app/skills.json",
					SubPath:   "skills.json",
				},
			}
		}
	}

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:            name,
			Namespace:       dac.Namespace,
			Labels:          labels,
			OwnerReferences: ownerRefs,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Strategy: appsv1.DeploymentStrategy{
				Type: "RollingUpdate",
			},
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: podSpec,
			},
		},
	}
	return deployment, nil
}

func (h *DataAgentContainerGenerator) GenerateDataAgentContainerDeployment(ctx context.Context, dac *dacv1alpha1.DataAgentContainer, labels map[string]string, ownerRefs []metav1.OwnerReference) (*appsv1.Deployment, error) {

	name := h.GenerateDataAgentContainerDeploymentName(dac)

	serviceName := h.GenerateDataAgentContainerServiceName(dac)

	replicas := int32(1)

	if dac.Spec.AgentCard.Skills != nil {
		err := h.createConfigMapForSkills(ctx, dac)
		if err != nil {
			return nil, err
		}
	}

	dacConfig, err := h.getDACConfig(ctx)
	if err != nil {
		return nil, err
	}

	// Default images for normal type; override from dacConfig only when non-empty
	orchestratorAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/orchestrator-agent:v0.6.0-amd64"
	expertAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/expert-agent:v0.6.0-amd64"

	if dacConfig != nil {
		if dacConfig.OrchestratorAgentImage != "" {
			orchestratorAgentImage = dacConfig.OrchestratorAgentImage
		}
		if dacConfig.ExpertAgentImage != "" {
			expertAgentImage = dacConfig.ExpertAgentImage
		}
	}

	plannerLLMConfig, err := h.getPlannerLLMConfig(ctx, dac)
	if err != nil {
		return nil, err
	}

	expertLLMConfig, err := h.getExpertLLMConfig(ctx, dac)
	if err != nil {
		return nil, err
	}

	orchestratorAgentArgs := h.generateOrchestratorAgentArgs(dac, plannerLLMConfig, dacConfig)

	expertAgentArgs := h.generateExpertAgentArgs(dac, expertLLMConfig, dacConfig)

	ddDescriptorTypes := ""

	podSpec := corev1.PodSpec{
		// ImagePullSecrets: imagePullSecrets,
		Containers: []corev1.Container{
			{
				Name:            "orchestrator",
				Image:           orchestratorAgentImage,
				ImagePullPolicy: corev1.PullIfNotPresent,
				Args:            orchestratorAgentArgs,
				Ports: []corev1.ContainerPort{
					{
						Name:          "orchestrator",
						ContainerPort: 10100,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateOrchestratorAgentEnvs(dac, serviceName, ddDescriptorTypes, dacConfig),
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("2000m"),
						corev1.ResourceMemory: resource.MustParse("8000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("1000Mi"),
					},
				},
			},
			{
				Name:            "expert",
				Image:           expertAgentImage,
				ImagePullPolicy: corev1.PullIfNotPresent,
				Args:            expertAgentArgs,
				Ports: []corev1.ContainerPort{
					{
						Name:          "expert",
						ContainerPort: 10101,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateExpertAgentEnvs(dac, serviceName, ddDescriptorTypes, dacConfig),
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("2000m"),
						corev1.ResourceMemory: resource.MustParse("8000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("1000Mi"),
					},
				},
			},
		},
	}

	if dac.Spec.AgentCard.Skills != nil {
		skillsConfigMapName := DataAgentContainerResourceName(dac)

		podSpec.Volumes = []corev1.Volume{
			{
				Name: "skills-config",
				VolumeSource: corev1.VolumeSource{
					ConfigMap: &corev1.ConfigMapVolumeSource{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: skillsConfigMapName,
						},
					},
				},
			},
		}

		for i := range podSpec.Containers {
			podSpec.Containers[i].VolumeMounts = []corev1.VolumeMount{
				{
					Name:      "skills-config",
					MountPath: "/app/skills.json",
					SubPath:   "skills.json",
				},
			}
		}
	}

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:            name,
			Namespace:       dac.Namespace,
			Labels:          labels,
			OwnerReferences: ownerRefs,
		},
		Spec: appsv1.DeploymentSpec{
			Replicas: &replicas,
			Strategy: appsv1.DeploymentStrategy{
				Type: "RollingUpdate",
			},
			Selector: &metav1.LabelSelector{
				MatchLabels: labels,
			},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: labels,
				},
				Spec: podSpec,
			},
		},
	}
	return deployment, nil
}
