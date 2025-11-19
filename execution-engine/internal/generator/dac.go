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
	ObservationBaseURL     string
	ObservationSecretKey   string
	ObservationPublicKey   string
	RedisHost              string
	RedisPort              string
	RedisPassword          string
	DataServicesURL        string
	ExpertAgentRegistry    string
	OrchestratorAgentImage string
	ExpertAgentImage       string
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
		// If no resource we need to create.
		if errors.IsNotFound(err) {
			err := h.K8sServices.CreateService(dac.Namespace, service)
			if err != nil {
				return err
			}
		}
	}

	deployment, err := h.GenerateDataAgentContainerDeployment(ctx, dac, labels, ownerRefs)
	if err != nil {
		return err
	}

	deploymentName := h.GenerateDataAgentContainerDeploymentName(dac)
	if _, err := h.K8sServices.GetDeployment(dac.Namespace, deploymentName); err != nil {
		// If no resource we need to create.
		if errors.IsNotFound(err) {
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

func (h *DataAgentContainerGenerator) GenerateDataAgentContainerServiceName(dac *dacv1alpha1.DataAgentContainer) string {
	serviceName := fmt.Sprintf("%s-%s", dac.Name, "service")
	return serviceName
}

func (h *DataAgentContainerGenerator) generateExpertAgentEnvs(dac *dacv1alpha1.DataAgentContainer, serviceName string, ddDescriptorTypes string, dacConfig *DACConfig) []corev1.EnvVar {
	envs := []corev1.EnvVar{}

	agentCardURL := serviceName + "." + dac.Namespace + ".svc.cluster.local"

	dataServicesURL := "http://data-services.dac.svc.cluster.local:8000"

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
		Name:  "DD_NAMESPACE",
		Value: dac.Namespace,
	})

	dataDescriptor := strings.Join(dac.Spec.DataPolicy.SourceNameSelector, ",")
	envs = append(envs, corev1.EnvVar{
		Name:  "Data_Descriptor",
		Value: dataDescriptor,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "DataServicesURL",
		Value: dataServicesURL,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "DescriptorTypes",
		Value: ddDescriptorTypes,
	})

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

	dataServicesURL := ""
	expertAgentRegistry := ""

	if dacConfig != nil {
		dataServicesURL = dacConfig.DataServicesURL
		expertAgentRegistry = dacConfig.ExpertAgentRegistry
	} else {
		dataServicesURL = "http://data-services.dac.svc.cluster.local:8000"
		expertAgentRegistry = "http://expert-registry.dac.svc.cluster.local:8000"
	}

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Host",
		Value: agentCardURL,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "Agent_Port",
		Value: "10100",
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "AgentRegistry",
		Value: expertAgentRegistry,
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
		Name:  "DD_NAMESPACE",
		Value: dac.Namespace,
	})

	dataDescriptor := strings.Join(dac.Spec.DataPolicy.SourceNameSelector, ",")
	envs = append(envs, corev1.EnvVar{
		Name:  "Data_Descriptor",
		Value: dataDescriptor,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "DataServicesURL",
		Value: dataServicesURL,
	})

	envs = append(envs, corev1.EnvVar{
		Name:  "DescriptorTypes",
		Value: ddDescriptorTypes,
	})

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
				Name:      fmt.Sprintf("%s-skills", dac.Name),
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
		ObservationBaseURL:     configMap.Data["observation-base-url"],
		ObservationSecretKey:   configMap.Data["observation-secret-key"],
		ObservationPublicKey:   configMap.Data["observation-public-key"],
		RedisHost:              configMap.Data["redis-host"],
		RedisPort:              configMap.Data["redis-port"],
		RedisPassword:          configMap.Data["redis-password"],
		DataServicesURL:        configMap.Data["data-services-url"],
		ExpertAgentRegistry:    configMap.Data["expert-agent-registry"],
		OrchestratorAgentImage: configMap.Data["orchestrator-agent-image"],
		ExpertAgentImage:       configMap.Data["expert-agent-image"],
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

// getDescriptorType get dd from dac
func (h *DataAgentContainerGenerator) getDDDescriptorTypes(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) (string, error) {
	// return "dd1name:type:host:mysql-server:port:3306:user:root:password:123:database:dactest;dd2name:type:host:mysql-server:port:3306:user:root:password:123:database:dactest"

	// Concatenate the strings in the original order
	var resultBuilder strings.Builder
	first := true

	for _, item := range dac.Spec.DataPolicy.SourceNameSelector {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}

		dataDescriptor := &dacv1alpha1.DataDescriptor{}
		err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: item, Namespace: dac.Namespace}, dataDescriptor)
		if err != nil {
			return "", fmt.Errorf("failed to get DataDescriptor %s: %v", item, err)
		}

		if !first {
			resultBuilder.WriteString(";")
		}

		resultBuilder.WriteString(item)
		resultBuilder.WriteString(":")
		resultBuilder.WriteString(dataDescriptor.Spec.DescriptorType)

		if len(dataDescriptor.Spec.Sources) > 0 && len(dataDescriptor.Spec.Sources[0].Metadata) > 0 {
			for key, value := range dataDescriptor.Spec.Sources[0].Metadata {
				resultBuilder.WriteString(":")
				resultBuilder.WriteString(key)
				resultBuilder.WriteString(":")
				resultBuilder.WriteString(value)
			}
		}

		first = false
	}

	return resultBuilder.String(), nil
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

func (h *DataAgentContainerGenerator) GenerateDataAgentContainerDeploymentName(dac *dacv1alpha1.DataAgentContainer) string {
	deploymentName := fmt.Sprintf("%s-%s", dac.Name, "deployment")
	return deploymentName
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

	orchestratorAgentImage := ""
	expertAgentImage := ""

	if dacConfig != nil {
		orchestratorAgentImage = dacConfig.OrchestratorAgentImage
		expertAgentImage = dacConfig.ExpertAgentImage
	} else {
		orchestratorAgentImage = "registry.cn-shanghai.aliyuncs.com/jamesxiong/orchestrator-agent:v0.2.0-amd64"
		expertAgentImage = "registry.cn-shanghai.aliyuncs.com/jamesxiong/expert-agent:v0.2.0-amd64"
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

	ddDescriptorTypes, err := h.getDDDescriptorTypes(ctx, dac)
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
		skillsConfigMapName := fmt.Sprintf("%s-skills", dac.Name)

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
