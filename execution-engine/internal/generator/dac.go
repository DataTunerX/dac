package generator

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"

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
	TDBBaseURL                   string
	DSOrchestratorAgentRegistry  string
	BIZOrchestratorAgentRegistry string
	OrchestratorAgentImage       string
	ExpertAgentImage             string
	DSDataServicesImage          string
	CodeAgentImage               string
	DocAgentImage                string
	DDSyncObserverImage          string
	ImagePullPolicy              corev1.PullPolicy
	// SkillAgentImage is used by dacType=skill single-container Deployments.
	SkillAgentImage string
	// SkillCmdTimeoutSeconds bounds a single skill subprocess. The skill-agent
	// default is 30s, which is too short for skills that shell out to do real
	// work (wwybsj-build runs registry writes and gateway verification).
	SkillCmdTimeoutSeconds string
}

func (h *DataAgentContainerGenerator) Do(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) error {
	logger := h.Logger.WithValues("namespace", dac.Namespace, "name", dac.Name, "dacType", dac.Spec.DACType)
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

	// Incremental branch: dacType=skill uses a single-port Service + skill-agent Deployment.
	// ds/normal paths below are left unchanged.
	if dac.Spec.DACType == "skill" {
		logger.Info("Entering skill DAC branch: single skill-agent container, register to biz Redis db")
		service := h.GenerateSkillDataAgentContainerService(dac, labels, ownerRefs)
		if err := h.K8sServices.CreateOrUpdateService(dac.Namespace, service); err != nil {
			logger.Error(err, "Failed to CreateOrUpdate skill DAC Service")
			return err
		}
		deployment, err := h.GenerateSkillDataAgentContainerDeployment(ctx, dac, labels, ownerRefs)
		if err != nil {
			logger.Error(err, "Failed to generate skill DAC Deployment")
			return err
		}
		if err := h.K8sServices.CreateOrUpdateDeployment(dac.Namespace, deployment); err != nil {
			logger.Error(err, "Failed to CreateOrUpdate skill DAC Deployment")
			return err
		}
		logger.Info("Skill DAC Service and Deployment reconciled successfully")
		return nil
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
		// Use CreateOrUpdate so that AgentCard/syncPolicy changes trigger deployment update
		if err := h.K8sServices.CreateOrUpdateDeployment(dac.Namespace, deployment); err != nil {
			return err
		}
	}

	if dac.Spec.DACType == "normal" {
		deployment, err := h.GenerateDataAgentContainerDeployment(ctx, dac, labels, ownerRefs)
		if err != nil {
			return err
		}

		// Reconcile updates so skillPolicy, AgentCard, model, and resource changes
		// reach an existing normal DAC Deployment and trigger a rollout.
		if err := h.K8sServices.CreateOrUpdateDeployment(dac.Namespace, deployment); err != nil {
			return err
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

func (h *DataAgentContainerGenerator) generateExpertAgentEnvs(dac *dacv1alpha1.DataAgentContainer, serviceName string, ddDescriptorTypes string, dacConfig *DACConfig, llmConfig *LLMConfig) []corev1.EnvVar {
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

	envs = append(envs, corev1.EnvVar{
		Name:  "REGISTER_AGENT",
		Value: "false",
	})

	if dac.Spec.DACType == "ds" {
		dataServicesURL := "http://localhost:8000"
		envs = append(envs, corev1.EnvVar{
			Name:  "DataServicesURL",
			Value: dataServicesURL,
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
		envs = appendTDBBaseURLEnv(envs, dacConfig)
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

	envs = appendEnableThinkingEnv(envs, llmConfig)

	return envs
}

func (h *DataAgentContainerGenerator) generateOrchestratorAgentEnvs(dac *dacv1alpha1.DataAgentContainer, serviceName string, ddDescriptorTypes string, dacConfig *DACConfig, llmConfig *LLMConfig) []corev1.EnvVar {
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
		envs = appendTDBBaseURLEnv(envs, dacConfig)
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

	envs = appendEnableThinkingEnv(envs, llmConfig)

	return envs
}

// agentCardSkillsSHA256 is a stable checksum of AgentCard.skills JSON for rolling Pods when skills change.
func agentCardSkillsSHA256(dac *dacv1alpha1.DataAgentContainer) string {
	if dac.Spec.AgentCard.Skills == nil {
		return ""
	}
	skillsJSON, err := json.Marshal(dac.Spec.AgentCard.Skills)
	if err != nil {
		return ""
	}
	sum := sha256.Sum256(skillsJSON)
	return hex.EncodeToString(sum[:])
}

func podTemplateObjectMeta(labels map[string]string, dac *dacv1alpha1.DataAgentContainer) metav1.ObjectMeta {
	om := metav1.ObjectMeta{Labels: labels}
	if dac.Spec.AgentCard.Skills != nil {
		if h := agentCardSkillsSHA256(dac); h != "" {
			if om.Annotations == nil {
				om.Annotations = map[string]string{}
			}
			om.Annotations["dac.dac.io/skills-json-sha256"] = h
		}
	}
	return om
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

		return h.K8sServices.CreateOrUpdateConfigMap(dac.Namespace, configMap)
	}
	return nil
}

// getDACConfig reads cluster-wide DAC settings (images, data-services-url, dd-sync-observer-image, …)
// from ConfigMap dac-configuration in namespace "dac". If that ConfigMap is missing, returns (nil, nil).
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
		TDBBaseURL:                   configMap.Data["tdb-url"],
		BIZOrchestratorAgentRegistry: configMap.Data["biz-orchestrator-agent-registry"],
		DSOrchestratorAgentRegistry:  configMap.Data["orchestrator-agent-registry"],
		OrchestratorAgentImage:       configMap.Data["orchestrator-agent-image"],
		ExpertAgentImage:             configMap.Data["expert-agent-image"],
		DSDataServicesImage:          configMap.Data["ds-data-services-image"],
		CodeAgentImage:               configMap.Data["code-agent-image"],
		DocAgentImage:                configMap.Data["doc-agent-image"],
		DDSyncObserverImage:          configMap.Data["dd-sync-observer-image"],
		ImagePullPolicy:              corev1.PullPolicy(configMap.Data["image-pull-policy"]),
		SkillAgentImage:              configMap.Data["skill-agent-image"],
		SkillCmdTimeoutSeconds:       configMap.Data["skill-cmd-timeout-sec"],
	}, nil
}

func resolveDACImagePullPolicy(config *DACConfig) corev1.PullPolicy {
	if config != nil {
		switch config.ImagePullPolicy {
		case corev1.PullAlways, corev1.PullIfNotPresent, corev1.PullNever:
			return config.ImagePullPolicy
		}
	}
	return corev1.PullIfNotPresent
}

func appendTDBBaseURLEnv(envs []corev1.EnvVar, config *DACConfig) []corev1.EnvVar {
	if config != nil && config.TDBBaseURL != "" {
		envs = append(envs, corev1.EnvVar{Name: "TDB_BASE_URL", Value: config.TDBBaseURL})
	}
	return envs
}

// rejectsEnableThinking reports whether the LLM endpoint refuses the
// enable_thinking extra_body key. It is a DashScope/Qwen extension; the real
// OpenAI API answers 400 "Unknown parameter: 'enable_thinking'".
func rejectsEnableThinking(llmConfig *LLMConfig) bool {
	if llmConfig == nil {
		return false
	}
	return strings.Contains(strings.ToLower(llmConfig.BaseURL), "api.openai.com")
}

// appendEnableThinkingEnv disables the enable_thinking extra_body param for
// endpoints that reject it. Agents default it on (ENABLE_THINKING_PARAM unset
// means true), so without this every request to such an endpoint fails.
func appendEnableThinkingEnv(envs []corev1.EnvVar, llmConfig *LLMConfig) []corev1.EnvVar {
	if rejectsEnableThinking(llmConfig) {
		envs = append(envs, corev1.EnvVar{Name: "ENABLE_THINKING_PARAM", Value: "false"})
	}
	return envs
}

// getPlannerLLMConfig get data from configmap
func (h *DataAgentContainerGenerator) getPlannerLLMConfig(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) (*LLMConfig, error) {
	configMap := &corev1.ConfigMap{}

	err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: dac.Spec.Model.PlannerLLM, Namespace: "dac"}, configMap)
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

	err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: dac.Spec.Model.ExpertLLM, Namespace: "dac"}, configMap)
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

// hasSyncPolicyEnabled returns true if any DataDescriptor referenced by the DAC
// has spec.syncPolicy.enabled == true.
//
// Contract: DataDescriptors listed in dataPolicy.sourceNameSelector are resolved in
// dac.Namespace only (same namespace as the DataAgentContainer). Cross-namespace DD
// refs are not supported here; dd-sync-observer RBAC is namespaced accordingly.
func (h *DataAgentContainerGenerator) hasSyncPolicyEnabled(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) (bool, string, string) {
	for _, item := range dac.Spec.DataPolicy.SourceNameSelector {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		dd := &dacv1alpha1.DataDescriptor{}
		if err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: item, Namespace: dac.Namespace}, dd); err != nil {
			continue
		}
		if dd.Spec.SyncPolicy != nil && dd.Spec.SyncPolicy.Enabled {
			return true, dac.Namespace, item
		}
	}
	return false, "", ""
}

// resolveDataDescriptorKey matches data-services / dac-data-services DATA_DESCRIPTOR:
// first SyncPolicy-enabled DD in sourceNameSelector if any, else first selector entry;
// hyphens replaced with underscores (entire string).
func (h *DataAgentContainerGenerator) resolveDataDescriptorKey(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) string {
	enabled, _, ddName := h.hasSyncPolicyEnabled(ctx, dac)
	if enabled && strings.TrimSpace(ddName) != "" {
		return strings.ReplaceAll(dac.Namespace+"_"+ddName, "-", "_")
	}
	ddName = ""
	if len(dac.Spec.DataPolicy.SourceNameSelector) > 0 {
		ddName = strings.TrimSpace(dac.Spec.DataPolicy.SourceNameSelector[0])
	}
	return strings.ReplaceAll(dac.Namespace+"_"+ddName, "-", "_")
}

// buildObserverSidecar returns the dd-sync-observer container if any referenced DD
// has syncPolicy.enabled and dac-configuration provides dd-sync-observer-image; otherwise nil.
func (h *DataAgentContainerGenerator) buildObserverSidecar(ctx context.Context, dac *dacv1alpha1.DataAgentContainer, dacConfig *DACConfig) *corev1.Container {
	enabled, ddNamespace, ddName := h.hasSyncPolicyEnabled(ctx, dac)
	if !enabled {
		return nil
	}

	observerImage := ""
	if dacConfig != nil {
		observerImage = strings.TrimSpace(dacConfig.DDSyncObserverImage)
	}
	if observerImage == "" {
		h.Logger.Info(
			"dd-sync-observer sidecar skipped: dd-sync-observer-image not set or empty in dac-configuration",
			"feature", "dd_sync_observer_sidecar",
			"dac", dac.Name,
			"dacNamespace", dac.Namespace,
		)
		return nil
	}

	// Observer shares the ds DAC pod with the dac-data-services container (port 8000).
	// Do not use dac-configuration data-services-url here: that points at the cluster backend
	// and skips in-pod Data-Descriptor validation / proxy behavior.
	const observerLocalDataServicesURL = "http://localhost:8000"

	schedule := "6h"
	for _, item := range dac.Spec.DataPolicy.SourceNameSelector {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		dd := &dacv1alpha1.DataDescriptor{}
		if err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: item, Namespace: dac.Namespace}, dd); err != nil {
			continue
		}
		if dd.Spec.SyncPolicy != nil && dd.Spec.SyncPolicy.Schedule != "" {
			schedule = dd.Spec.SyncPolicy.Schedule
			break
		}
	}

	dataDescriptor := h.resolveDataDescriptorKey(ctx, dac)
	envs := []corev1.EnvVar{
		{Name: "DD_NAMESPACE", Value: ddNamespace},
		{Name: "DD_NAME", Value: ddName},
		{Name: "DATA_DESCRIPTOR", Value: dataDescriptor},
		{Name: "DATA_SERVICES_URL", Value: observerLocalDataServicesURL},
		{Name: "SYNC_SCHEDULE", Value: schedule},
		{Name: "PYTHONUNBUFFERED", Value: "1"},
	}

	return &corev1.Container{
		Name:            "dd-sync-observer",
		Image:           observerImage,
		ImagePullPolicy: resolveDACImagePullPolicy(dacConfig),
		Command:         []string{"python", "-m", "data_sinkers.observer"},
		Env:             envs,
		Resources: corev1.ResourceRequirements{
			Limits: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("1000m"),
				corev1.ResourceMemory: resource.MustParse("2000Mi"),
			},
			Requests: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("100m"),
				corev1.ResourceMemory: resource.MustParse("256Mi"),
			},
		},
	}
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

func (h *DataAgentContainerGenerator) generateDataServicesEnvs(ctx context.Context, dac *dacv1alpha1.DataAgentContainer, dacConfig *DACConfig) ([]corev1.EnvVar, error) {
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

	dataDescriptor := h.resolveDataDescriptorKey(ctx, dac)

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
	dataServicesImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/dac-data-services:v0.9.0-amd64"
	orchestratorAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/orchestrator-agent:v0.8.0-amd64"
	expertAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/expert-agent:v0.8.0-amd64"
	codeAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/code-agent:v0.7.0-amd64"
	docAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/doc-agent:v0.7.0-amd64"

	if dacConfig != nil {
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

	dataServicesEnvs, err := h.generateDataServicesEnvs(ctx, dac, dacConfig)
	if err != nil {
		return nil, err
	}

	podSpec := corev1.PodSpec{
		// ImagePullSecrets: imagePullSecrets,
		Containers: []corev1.Container{
			{
				Name:            "orchestrator",
				Image:           orchestratorAgentImage,
				ImagePullPolicy: resolveDACImagePullPolicy(dacConfig),
				Args:            orchestratorAgentArgs,
				Ports: []corev1.ContainerPort{
					{
						Name:          "orchestrator",
						ContainerPort: 10100,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateOrchestratorAgentEnvs(dac, serviceName, ddDescriptorTypes, dacConfig, plannerLLMConfig),
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("1000m"),
						corev1.ResourceMemory: resource.MustParse("2000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("256Mi"),
					},
				},
			},
			{
				Name:            "expert",
				Image:           actualExpertImage,
				ImagePullPolicy: resolveDACImagePullPolicy(dacConfig),
				Args:            expertAgentArgs,
				Ports: []corev1.ContainerPort{
					{
						Name:          "expert",
						ContainerPort: 10101,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateExpertAgentEnvs(dac, serviceName, ddDescriptorTypes, dacConfig, expertLLMConfig),
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("1000m"),
						corev1.ResourceMemory: resource.MustParse("2000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("256Mi"),
					},
				},
			},
			{
				Name:            "data-services",
				Image:           dataServicesImage,
				ImagePullPolicy: resolveDACImagePullPolicy(dacConfig),
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
						corev1.ResourceMemory: resource.MustParse("256Mi"),
					},
				},
			},
		},
	}

	if err := configureLocalSkillAttachments(dac, &podSpec); err != nil {
		return nil, err
	}

	// Add dd-sync-observer sidecar when any referenced DD has syncPolicy.enabled
	if observerContainer := h.buildObserverSidecar(ctx, dac, dacConfig); observerContainer != nil {
		podSpec.Containers = append(podSpec.Containers, *observerContainer)
		h.Logger.Info(
			"dd-sync-observer sidecar appended to ds DAC Pod (DD syncPolicy.enabled)",
			"feature", "dd_sync_observer_sidecar",
			"dac", dac.Name,
			"dacNamespace", dac.Namespace,
			"sidecarContainer", observerContainer.Name,
			"sidecarImage", observerContainer.Image,
		)
	}

	if dac.Spec.AgentCard.Skills != nil {
		skillsConfigMapName := DataAgentContainerResourceName(dac)

		podSpec.Volumes = append(podSpec.Volumes,
			corev1.Volume{
				Name: "skills-config",
				VolumeSource: corev1.VolumeSource{
					ConfigMap: &corev1.ConfigMapVolumeSource{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: skillsConfigMapName,
						},
					},
				},
			},
		)

		for i := range podSpec.Containers {
			podSpec.Containers[i].VolumeMounts = append(podSpec.Containers[i].VolumeMounts,
				corev1.VolumeMount{
					Name:      "skills-config",
					MountPath: "/app/skills.json",
					SubPath:   "skills.json",
				},
			)
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
				ObjectMeta: podTemplateObjectMeta(labels, dac),
				Spec:       podSpec,
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
				ImagePullPolicy: resolveDACImagePullPolicy(dacConfig),
				Args:            orchestratorAgentArgs,
				Ports: []corev1.ContainerPort{
					{
						Name:          "orchestrator",
						ContainerPort: 10100,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateOrchestratorAgentEnvs(dac, serviceName, ddDescriptorTypes, dacConfig, plannerLLMConfig),
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("1000m"),
						corev1.ResourceMemory: resource.MustParse("2000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("256Mi"),
					},
				},
			},
			{
				Name:            "expert",
				Image:           expertAgentImage,
				ImagePullPolicy: resolveDACImagePullPolicy(dacConfig),
				Args:            expertAgentArgs,
				Ports: []corev1.ContainerPort{
					{
						Name:          "expert",
						ContainerPort: 10101,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateExpertAgentEnvs(dac, serviceName, ddDescriptorTypes, dacConfig, expertLLMConfig),
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("1000m"),
						corev1.ResourceMemory: resource.MustParse("2000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("256Mi"),
					},
				},
			},
		},
	}

	if err := configureLocalSkillAttachments(dac, &podSpec); err != nil {
		return nil, err
	}

	if dac.Spec.AgentCard.Skills != nil {
		skillsConfigMapName := DataAgentContainerResourceName(dac)

		podSpec.Volumes = append(podSpec.Volumes,
			corev1.Volume{
				Name: "skills-config",
				VolumeSource: corev1.VolumeSource{
					ConfigMap: &corev1.ConfigMapVolumeSource{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: skillsConfigMapName,
						},
					},
				},
			},
		)

		for i := range podSpec.Containers {
			podSpec.Containers[i].VolumeMounts = append(podSpec.Containers[i].VolumeMounts,
				corev1.VolumeMount{
					Name:      "skills-config",
					MountPath: "/app/skills.json",
					SubPath:   "skills.json",
				},
			)
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
				ObjectMeta: podTemplateObjectMeta(labels, dac),
				Spec:       podSpec,
			},
		},
	}
	return deployment, nil
}

// GenerateSkillDataAgentContainerService exposes only port 10100 for skill-agent.
// Kept separate from GenerateDataAgentContainerService so ds/normal dual-port logic is unchanged.
func (h *DataAgentContainerGenerator) GenerateSkillDataAgentContainerService(dac *dacv1alpha1.DataAgentContainer, labels map[string]string, ownerRefs []metav1.OwnerReference) *corev1.Service {
	serviceName := h.GenerateDataAgentContainerServiceName(dac)
	targetPort := intstr.FromInt(10100)
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
					Name:       "skill",
					TargetPort: targetPort,
				},
			},
			Selector: labels,
		},
	}
}

// skillRefForEnv is the SKILLS env JSON element consumed by skill-agent skill_download.
type skillRefForEnv struct {
	Namespace string `json:"namespace"`
	Name      string `json:"name"`
	Version   string `json:"version"`
}

const (
	localSkillsVolumeName = "local-skills"
	localSkillsMountPath  = "/var/run/dac-skills"
)

// buildSkillsEnvJSON builds SKILLS from skillPolicy (source of truth for zip download).
func buildSkillsEnvJSON(dac *dacv1alpha1.DataAgentContainer) (string, error) {
	refs := make([]skillRefForEnv, 0, len(dac.Spec.SkillPolicy.Skills))
	for _, s := range dac.Spec.SkillPolicy.Skills {
		ns := strings.TrimSpace(s.Namespace)
		name := strings.TrimSpace(s.Name)
		if ns == "" || name == "" {
			continue
		}
		refs = append(refs, skillRefForEnv{
			Namespace: ns,
			Name:      name,
			Version:   strings.TrimSpace(s.Version),
		})
	}
	b, err := json.Marshal(refs)
	if err != nil {
		return "", err
	}
	return string(b), nil
}

// configureLocalSkillAttachments mounts an ephemeral skill directory into the
// orchestrator and tells its existing startup downloader/SkillRunner to load
// the packages selected through skillPolicy. Dedicated dacType=skill workloads
// keep using their single skill-agent container and do not pass through here.
func configureLocalSkillAttachments(dac *dacv1alpha1.DataAgentContainer, podSpec *corev1.PodSpec) error {
	if dac.Spec.DACType == "skill" || len(dac.Spec.SkillPolicy.Skills) == 0 {
		return nil
	}

	skillsJSON, err := buildSkillsEnvJSON(dac)
	if err != nil {
		return fmt.Errorf("marshal local skill attachments: %w", err)
	}

	for i := range podSpec.Containers {
		if podSpec.Containers[i].Name != "orchestrator" {
			continue
		}
		podSpec.Containers[i].Env = append(podSpec.Containers[i].Env,
			corev1.EnvVar{Name: "ENABLE_LOCAL_SKILLS", Value: "true"},
			corev1.EnvVar{Name: "LOCAL_SKILL_FORCE_ATTACHED", Value: "true"},
			corev1.EnvVar{Name: "SKILLS", Value: skillsJSON},
			corev1.EnvVar{Name: "SKILL_HUB_URL", Value: "http://skill-hub.dac.svc.cluster.local:8000"},
			corev1.EnvVar{Name: "SKILLS_DOWNLOAD_DIR", Value: localSkillsMountPath},
			corev1.EnvVar{Name: "LOCAL_SKILLS_DIR", Value: localSkillsMountPath},
			corev1.EnvVar{Name: "SKILL_DOWNLOAD_OVERWRITE", Value: "true"},
			corev1.EnvVar{Name: "SKILL_DOWNLOAD_CONCURRENCY", Value: "8"},
			// Local attachments are an explicit set. Do not implicitly pull every
			// package published in the same Skill Hub namespace.
			corev1.EnvVar{Name: "SKILL_SYNC_WATCH_ALL", Value: "false"},
		)
		podSpec.Containers[i].VolumeMounts = append(
			podSpec.Containers[i].VolumeMounts,
			corev1.VolumeMount{Name: localSkillsVolumeName, MountPath: localSkillsMountPath},
		)
		podSpec.Volumes = append(podSpec.Volumes, corev1.Volume{
			Name: localSkillsVolumeName,
			VolumeSource: corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{},
			},
		})
		return nil
	}

	return fmt.Errorf("orchestrator container not found for local skill attachments")
}

// generateSkillAgentArgs builds skill-agent CLI args.
// Redis DB 2 matches biz-orchestrator-registry / biz-skill-agent so the agent registers to the biz center.
func (h *DataAgentContainerGenerator) generateSkillAgentArgs(dac *dacv1alpha1.DataAgentContainer, llmConfig *LLMConfig, dacConfig *DACConfig) []string {
	redisHost := "redis-server.dac.svc.cluster.local"
	redisPort := "6379"
	redisPassword := "123"
	if dacConfig != nil {
		if dacConfig.RedisHost != "" {
			redisHost = dacConfig.RedisHost
		}
		if dacConfig.RedisPort != "" {
			redisPort = dacConfig.RedisPort
		}
		if dacConfig.RedisPassword != "" {
			redisPassword = dacConfig.RedisPassword
		}
	}

	maxSteps := dac.Spec.ExpertAgentMaxSteps
	if maxSteps == "" {
		maxSteps = "20"
	}

	return []string{
		"--port", "10100",
		"--redis-host", redisHost,
		"--redis-port", redisPort,
		"--redis-db", "2",
		"--password", redisPassword,
		"--provider", llmConfig.Provider,
		"--api-key", llmConfig.APIKey,
		"--base-url", llmConfig.BaseURL,
		"--model", llmConfig.Model,
		"--max-steps", maxSteps,
	}
}

// generateSkillAgentEnvs builds env for the skill-agent container.
// REGISTER_AGENT=true + redis-db 2 → self-registers into the biz Redis registry.
func (h *DataAgentContainerGenerator) generateSkillAgentEnvs(dac *dacv1alpha1.DataAgentContainer, serviceName string, skillsJSON string, dacConfig *DACConfig, llmConfig *LLMConfig) []corev1.EnvVar {
	envs := []corev1.EnvVar{
		{Name: "Agent_Host", Value: fmt.Sprintf("%s.%s.svc.cluster.local", serviceName, dac.Namespace)},
		{Name: "Agent_Port", Value: "10100"},
		{Name: "Agent_Name", Value: dac.Spec.AgentCard.Name},
		{Name: "Agent_Description", Value: dac.Spec.AgentCard.Description},
		{Name: "REGISTER_AGENT", Value: "true"},
		{Name: "SKILLS", Value: skillsJSON},
		{Name: "SKILL_HUB_URL", Value: "http://skill-hub.dac.svc.cluster.local:8000"},
		{Name: "SKILLS_DOWNLOAD_DIR", Value: "/app/skills/"},
		{Name: "SKILL_DOWNLOAD_OVERWRITE", Value: "true"},
		{Name: "SKILL_DOWNLOAD_CONCURRENCY", Value: "8"},
	}
	// A skillPolicy is an explicit set, exactly like the local attachments
	// handled in configureLocalSkillAttachments. The sync thread defaults
	// SKILL_SYNC_WATCH_ALL to true, which subscribes to the whole Skill Hub
	// namespace and pulls every package regardless of SKILLS -- so an agent
	// bound to one skill still loaded every tdb-* skill and then claimed those
	// domains in its capability check, making every agent look equally capable
	// and collapsing routing to whichever answered first.
	//
	// Only pin it when the policy actually names skills: with an empty policy
	// the agent has nothing of its own, and disabling the watch would leave it
	// with no skills at all.
	if len(dac.Spec.SkillPolicy.Skills) > 0 {
		envs = append(envs, corev1.EnvVar{Name: "SKILL_SYNC_WATCH_ALL", Value: "false"})
	}
	if dac.Spec.ExpertAgentMaxSteps != "" {
		envs = append(envs, corev1.EnvVar{Name: "LOCAL_SKILL_MAX_STEPS", Value: dac.Spec.ExpertAgentMaxSteps})
	}
	if dacConfig != nil && dacConfig.SkillCmdTimeoutSeconds != "" {
		envs = append(envs, corev1.EnvVar{Name: "LOCAL_SKILL_CMD_TIMEOUT_SEC", Value: dacConfig.SkillCmdTimeoutSeconds})
	}
	// Only the credential. A skill that shells out picks its own provider, base
	// URL and model in its shipped config (see the vendored tdb_pipeline
	// llm_config_common) -- exporting those here would override the skill from
	// outside and silently decide its LLM for it. The API key is different: it
	// is a secret, so it must come from the deployment rather than be committed
	// into a package that is published to the hub.
	if llmConfig != nil && llmConfig.APIKey != "" {
		envs = append(envs, corev1.EnvVar{Name: "TDB_LLM_API_KEY", Value: llmConfig.APIKey})
	}
	if dacConfig != nil {
		envs = appendTDBBaseURLEnv(envs, dacConfig)
		envs = append(envs,
			corev1.EnvVar{Name: "LANGFUSE_BASE_URL", Value: dacConfig.ObservationBaseURL},
			corev1.EnvVar{Name: "LANGFUSE_SECRET_KEY", Value: dacConfig.ObservationSecretKey},
			corev1.EnvVar{Name: "LANGFUSE_PUBLIC_KEY", Value: dacConfig.ObservationPublicKey},
		)
	}
	envs = appendEnableThinkingEnv(envs, llmConfig)

	return envs
}

// GenerateSkillDataAgentContainerDeployment creates a single-container skill-agent Deployment.
// Images come from dac-configuration skill-agent-image; SKILLS comes from skillPolicy (not agentCard).
func (h *DataAgentContainerGenerator) GenerateSkillDataAgentContainerDeployment(ctx context.Context, dac *dacv1alpha1.DataAgentContainer, labels map[string]string, ownerRefs []metav1.OwnerReference) (*appsv1.Deployment, error) {
	logger := h.Logger.WithValues("namespace", dac.Namespace, "name", dac.Name, "dacType", "skill")

	name := h.GenerateDataAgentContainerDeploymentName(dac)
	serviceName := h.GenerateDataAgentContainerServiceName(dac)
	replicas := int32(1)

	// Still project agentCard.skills into a ConfigMap for A2A card consistency.
	if dac.Spec.AgentCard.Skills != nil {
		if err := h.createConfigMapForSkills(ctx, dac); err != nil {
			return nil, err
		}
	}

	dacConfig, err := h.getDACConfig(ctx)
	if err != nil {
		return nil, err
	}

	// Default matches design; override from dac-configuration when present.
	skillAgentImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-agent:v0.11.0-amd64"
	if dacConfig != nil && dacConfig.SkillAgentImage != "" {
		skillAgentImage = dacConfig.SkillAgentImage
	}
	logger.Info("Skill DAC image resolved", "image", skillAgentImage)

	expertLLMConfig, err := h.getExpertLLMConfig(ctx, dac)
	if err != nil {
		return nil, err
	}

	skillsJSON, err := buildSkillsEnvJSON(dac)
	if err != nil {
		return nil, fmt.Errorf("marshal skillPolicy for SKILLS env: %w", err)
	}
	logger.Info("Skill DAC SKILLS env from skillPolicy", "skills", skillsJSON, "count", len(dac.Spec.SkillPolicy.Skills))

	if len(dac.Spec.SkillPolicy.Skills) == 0 {
		logger.Info("WARNING: skillPolicy.skills is empty; skill-agent will skip zip download")
	}

	// skill DAC has no orchestrator: LLM comes from expertLLM (not plannerLLM).
	args := h.generateSkillAgentArgs(dac, expertLLMConfig, dacConfig)
	envs := h.generateSkillAgentEnvs(dac, serviceName, skillsJSON, dacConfig, expertLLMConfig)

	podSpec := corev1.PodSpec{
		Containers: []corev1.Container{
			{
				Name:            "skill-agent",
				Image:           skillAgentImage,
				ImagePullPolicy: resolveDACImagePullPolicy(dacConfig),
				Args:            args,
				Ports: []corev1.ContainerPort{
					{Name: "skill", ContainerPort: 10100, Protocol: corev1.ProtocolTCP},
				},
				Env: envs,
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("1000m"),
						corev1.ResourceMemory: resource.MustParse("2000Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("256Mi"),
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
						LocalObjectReference: corev1.LocalObjectReference{Name: skillsConfigMapName},
					},
				},
			},
		}
		// Mount as skills-card.json so it does not collide with LOCAL_SKILLS_DIR=/app/skills/ zip directory.
		podSpec.Containers[0].VolumeMounts = []corev1.VolumeMount{
			{
				Name:      "skills-config",
				MountPath: "/app/skills-card.json",
				SubPath:   "skills.json",
			},
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
			Strategy: appsv1.DeploymentStrategy{Type: "RollingUpdate"},
			Selector: &metav1.LabelSelector{MatchLabels: labels},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: podTemplateObjectMeta(labels, dac),
				Spec:       podSpec,
			},
		},
	}
	return deployment, nil
}
