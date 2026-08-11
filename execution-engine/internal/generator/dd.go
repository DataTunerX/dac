package generator

import (
	"context"
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

// DataDescriptorHandler handles the reconciliation logic for DataDescriptor resources.
type DataDescriptorGenerator struct {
	K8sServices k8s.Services
	Kubeclient  client.Client
	Logger      logr.Logger
}

type DDConfig struct {
	ObservationBaseURL    string
	ObservationSecretKey  string
	ObservationPublicKey  string
	RedisHost             string
	RedisPort             string
	RedisPassword         string
	DataServicesURL       string
	DataSinkerJobImage    string
	DSDataServicesImage   string
	DataSinkerStatusImage string
	LLMConfig             string
}

func (h *DataDescriptorGenerator) Do(ctx context.Context, dd *dacv1alpha1.DataDescriptor, operation string) error {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("Generate DataDescriptor K8S resources", "operation", operation)

	labels := map[string]string{
		"data": dd.Name,
	}

	// 只有当 DD 对象存在且有 UID 时才设置 OwnerReference
	// 如果 DD 对象已被删除（UID 为空），则不设置 OwnerReference，资源独立存在直到删除任务完成
	var ownerRefs []metav1.OwnerReference
	if dd.UID != "" {
		isController := true
		ownerRefs = []metav1.OwnerReference{
			{
				APIVersion: dd.APIVersion,
				Kind:       dd.Kind,
				Name:       dd.Name,
				UID:        dd.UID,
				Controller: &isController,
			},
		}
	}

	service := h.GenerateDataDescriptorService(dd, labels, ownerRefs)
	serviceName := h.GenerateDataDescriptorServiceName(dd)
	if _, err := h.K8sServices.GetService(dd.Namespace, serviceName); err != nil {
		// If no resource we need to create.
		if errors.IsNotFound(err) {
			err := h.K8sServices.CreateService(dd.Namespace, service)
			if err != nil {
				return err
			}
		}
	}

	deployment, err := h.GenerateDataDescriptorDeployment(ctx, dd, labels, ownerRefs, operation)
	if err != nil {
		return err
	}

	deploymentName := h.GenerateDataDescriptorDeploymentName(dd)
	if _, err := h.K8sServices.GetDeployment(dd.Namespace, deploymentName); err != nil {
		// If no resource we need to create.
		if errors.IsNotFound(err) {
			err = h.K8sServices.CreateDeployment(dd.Namespace, deployment)
			if err != nil {
				return err
			}
		}
	}

	return nil
}

// DataDescriptorResourceName 返回 DD 相关 K8s 资源的统一名称，加 dd- 前缀以与 DAC 资源区分
func DataDescriptorResourceName(dd *dacv1alpha1.DataDescriptor) string {
	return "dd-" + dd.Name
}

func (h *DataDescriptorGenerator) GenerateDataDescriptorServiceName(dd *dacv1alpha1.DataDescriptor) string {
	return DataDescriptorResourceName(dd)
}

func (h *DataDescriptorGenerator) GenerateDataDescriptorService(dd *dacv1alpha1.DataDescriptor, labels map[string]string, ownerRefs []metav1.OwnerReference) *corev1.Service {
	serviceName := h.GenerateDataDescriptorServiceName(dd)
	dacDataServicesTargetPort := intstr.FromInt(8000)
	dataSinkerStatusTargetPort := intstr.FromInt(8001) // status 容器监听 8001
	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{
			Name:            serviceName,
			Namespace:       dd.Namespace,
			Labels:          labels,
			OwnerReferences: ownerRefs,
		},
		Spec: corev1.ServiceSpec{
			Type: corev1.ServiceTypeClusterIP,
			Ports: []corev1.ServicePort{
				{
					Port:       8000,
					Protocol:   corev1.ProtocolTCP,
					Name:       "dac-data-services",
					TargetPort: dacDataServicesTargetPort,
				},
				{
					Port:       8001,
					Protocol:   corev1.ProtocolTCP,
					Name:       "data-sinker-status",
					TargetPort: dataSinkerStatusTargetPort,
				},
			},
			Selector: labels,
		},
	}
}

func (h *DataDescriptorGenerator) generateDSDataServicesEnvs(dd *dacv1alpha1.DataDescriptor, ddConfig *DDConfig) []corev1.EnvVar {
	envs := []corev1.EnvVar{}

	dataServicesURL := ""
	if ddConfig != nil && ddConfig.DataServicesURL != "" {
		dataServicesURL = ddConfig.DataServicesURL
	} else {
		dataServicesURL = "http://data-services.dac.svc.cluster.local:8000"
	}
	envs = append(envs, corev1.EnvVar{
		Name:  "DATA_SERVICES",
		Value: dataServicesURL,
	})

	dataDescriptor := dd.Namespace + "_" + dd.Name
	dataDescriptor = strings.ReplaceAll(dataDescriptor, "-", "_")

	envs = append(envs, corev1.EnvVar{
		Name:  "DATA_DESCRIPTOR",
		Value: dataDescriptor,
	})

	return envs
}

func (h *DataDescriptorGenerator) generateDataSinkerJobEnvs(dd *dacv1alpha1.DataDescriptor, llmConfig *LLMConfig, ddConfig *DDConfig) ([]corev1.EnvVar, error) {
	envs := []corev1.EnvVar{}

	dataServicesURL := "http://localhost:8000"

	envs = append(envs, corev1.EnvVar{
		Name:  "DATA_SERVICES",
		Value: dataServicesURL,
	})

	dataDescriptor := dd.Namespace + "_" + dd.Name
	dataDescriptor = strings.ReplaceAll(dataDescriptor, "-", "_")

	envs = append(envs, corev1.EnvVar{
		Name:  "DATA_DESCRIPTOR",
		Value: dataDescriptor,
	})

	// 将 CRD 中定义的 descriptorType 传递给 data-sinker-job，
	// 以便在创建 semantic_domain 记录时保存类型信息
	if dd.Spec.DescriptorType != "" {
		envs = append(envs, corev1.EnvVar{
			Name:  "DESCRIPTOR_TYPE",
			Value: dd.Spec.DescriptorType,
		})
	}

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
	mineruDeviceMode := "cpu"
	if strings.EqualFold(dd.Spec.GPUEnabled, "yes") {
		mineruDeviceMode = "cuda"
	}
	envs = append(envs, corev1.EnvVar{
		Name:  "MINERU_DEVICE_MODE",
		Value: mineruDeviceMode,
	})
	// PDF_LOADER_POLICY selects PDF processing by capability: auto | ocr | text.
	// Derived from dd.Spec.PDFLoader. "ocr" forces OCR/layout parsing (even on CPU when
	// gpuEnabled=no); "text" forces embedded-text extraction only; anything else → "auto".
	pdfLoaderPolicy := strings.ToLower(strings.TrimSpace(dd.Spec.PDFLoader))
	switch pdfLoaderPolicy {
	case "ocr", "text":
		// keep
	case "mineru": // legacy alias
		pdfLoaderPolicy = "ocr"
	case "pymupdf": // legacy alias
		pdfLoaderPolicy = "text"
	default:
		pdfLoaderPolicy = "auto"
	}
	envs = append(envs, corev1.EnvVar{
		Name:  "PDF_LOADER_POLICY",
		Value: pdfLoaderPolicy,
	})
	envs = append(envs, corev1.EnvVar{
		Name:  "regroup_batch_size",
		Value: "10",
	})

	// CELERY_HTTPSERVER_API_BASE_URL: 从配置中获取或使用默认值
	celeryHTTPServerURL := ""
	if ddConfig != nil && ddConfig.ObservationBaseURL != "" {
		celeryHTTPServerURL = ddConfig.ObservationBaseURL
	} else {
		celeryHTTPServerURL = "http://celery-httpserver.dac:8000"
	}
	envs = append(envs, corev1.EnvVar{
		Name:  "CELERY_HTTPSERVER_API_BASE_URL",
		Value: celeryHTTPServerURL,
	})

	return envs, nil
}

// getObserveConfig get data from configmap
func (h *DataDescriptorGenerator) getConfig(ctx context.Context) (*DDConfig, error) {
	configMap := &corev1.ConfigMap{}

	configMapName := "dd-configuration"

	configMapNameSpace := "dac"

	err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: configMapName, Namespace: configMapNameSpace}, configMap)
	if err != nil {
		if errors.IsNotFound(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get ConfigMap: %v", err)
	}

	return &DDConfig{
		ObservationBaseURL:    configMap.Data["observation-base-url"],
		ObservationSecretKey:  configMap.Data["observation-secret-key"],
		ObservationPublicKey:  configMap.Data["observation-public-key"],
		RedisHost:             configMap.Data["redis-host"],
		RedisPort:             configMap.Data["redis-port"],
		RedisPassword:         configMap.Data["redis-password"],
		DataServicesURL:       configMap.Data["data-services-url"],
		DataSinkerJobImage:    configMap.Data["data-sinker-job-image"],
		DataSinkerStatusImage: configMap.Data["data-sinker-status-image"],
		DSDataServicesImage:   configMap.Data["dac-data-services-image"],
		LLMConfig:             configMap.Data["llm-config"],
	}, nil
}

func (h *DataDescriptorGenerator) getLLMConfig(ctx context.Context, dd *dacv1alpha1.DataDescriptor, ddConfig *DDConfig) (*LLMConfig, error) {
	configMap := &corev1.ConfigMap{}

	err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: ddConfig.LLMConfig, Namespace: "dac"}, configMap)
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

func (h *DataDescriptorGenerator) GenerateDataDescriptorDeploymentName(dd *dacv1alpha1.DataDescriptor) string {
	return DataDescriptorResourceName(dd)
}

func (h *DataDescriptorGenerator) GenerateDataDescriptorDeployment(ctx context.Context, dd *dacv1alpha1.DataDescriptor, labels map[string]string, ownerRefs []metav1.OwnerReference, operation string) (*appsv1.Deployment, error) {

	name := h.GenerateDataDescriptorDeploymentName(dd)

	replicas := int32(1)

	ddConfig, err := h.getConfig(ctx)
	if err != nil {
		return nil, err
	}

	// Default images
	defaultDataSinkerJobImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-job:v0.6.0-amd64"
	defaultDacDataServicesImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/dac-data-services:v0.6.0-amd64"
	defaultDataSinkerStatusImage := "registry.cn-shanghai.aliyuncs.com/jamesxiong/data-sinkers-status:v0.6.0-amd64"

	dataSinkerJobImage := defaultDataSinkerJobImage
	dacDataServicesImage := defaultDacDataServicesImage
	dataSinkerStatusImage := defaultDataSinkerStatusImage

	if ddConfig != nil {
		if ddConfig.DataSinkerJobImage != "" {
			dataSinkerJobImage = ddConfig.DataSinkerJobImage
		}
		if ddConfig.DSDataServicesImage != "" {
			dacDataServicesImage = ddConfig.DSDataServicesImage
		}
		if ddConfig.DataSinkerStatusImage != "" {
			dataSinkerStatusImage = ddConfig.DataSinkerStatusImage
		}
	}

	llmConfig, err := h.getLLMConfig(ctx, dd, ddConfig)
	if err != nil {
		return nil, err
	}

	dataSinkerEnvs, err := h.generateDataSinkerJobEnvs(dd, llmConfig, ddConfig)
	if err != nil {
		return nil, err
	}

	// Shared emptyDir volume for status file between data-sinker and status containers
	statusVolumeName := "status-dir"
	// ConfigMap volume for data-sinker job config (/app/data.json)
	jobConfigVolumeName := "job-config"
	jobConfigMapName := DataDescriptorResourceName(dd)

	podSpec := corev1.PodSpec{
		// ImagePullSecrets: imagePullSecrets,
		Volumes: []corev1.Volume{
			{
				Name: statusVolumeName,
				VolumeSource: corev1.VolumeSource{
					EmptyDir: &corev1.EmptyDirVolumeSource{},
				},
			},
			{
				Name: jobConfigVolumeName,
				VolumeSource: corev1.VolumeSource{
					ConfigMap: &corev1.ConfigMapVolumeSource{
						LocalObjectReference: corev1.LocalObjectReference{
							Name: jobConfigMapName,
						},
						Items: []corev1.KeyToPath{
							{
								Key:  "data.json",
								Path: "data.json",
							},
						},
					},
				},
			},
		},
		Containers: []corev1.Container{
			{
				Name:            "data-services",
				Image:           dacDataServicesImage,
				ImagePullPolicy: corev1.PullIfNotPresent,
				Ports: []corev1.ContainerPort{
					{
						Name:          "data-services",
						ContainerPort: 8000,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: h.generateDSDataServicesEnvs(dd, ddConfig),
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
			{
				Name:            "data-sinker-job",
				Image:           dataSinkerJobImage,
				ImagePullPolicy: corev1.PullIfNotPresent,
				Env:             dataSinkerEnvs,
				VolumeMounts: []corev1.VolumeMount{
					{
						Name:      statusVolumeName,
						MountPath: "/app/status",
					},
					{
						Name:      jobConfigVolumeName,
						MountPath: "/app/data.json",
						SubPath:   "data.json",
					},
				},
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU: resource.MustParse("2000m"),
						// MinerU PDF parsing (GPU/CPU mode) under multi-file batches can exceed 16Gi; 32Gi avoids cgroup OOM kills.
						corev1.ResourceMemory: resource.MustParse("32Gi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("500Mi"),
					},
				},
			},
			{
				Name:            "data-sinker-status",
				Image:           dataSinkerStatusImage,
				ImagePullPolicy: corev1.PullIfNotPresent,
				Ports: []corev1.ContainerPort{
					{
						Name:          "status",
						ContainerPort: 8001,
						Protocol:      corev1.ProtocolTCP,
					},
				},
				Env: []corev1.EnvVar{
					{
						Name:  "STATUS_FILE",
						Value: "/app/status/status.json",
					},
					{
						Name:  "PORT",
						Value: "8001",
					},
				},
				VolumeMounts: []corev1.VolumeMount{
					{
						Name:      statusVolumeName,
						MountPath: "/app/status",
					},
				},
				Resources: corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("200m"),
						corev1.ResourceMemory: resource.MustParse("256Mi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("50m"),
						corev1.ResourceMemory: resource.MustParse("64Mi"),
					},
				},
			},
		},
	}

	// Delete 操作是轻量的 API 调用（无 LLM/GPU/MinerU 解析），使用小资源避免占用大内存/GPU 节点。
	// 覆盖 data-sinker-job 容器的 resources 为轻量配置；GPU 分支也会跳过 Delete。
	if strings.EqualFold(operation, "Delete") {
		for i := range podSpec.Containers {
			if podSpec.Containers[i].Name == "data-sinker-job" {
				podSpec.Containers[i].Resources = corev1.ResourceRequirements{
					Limits: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("1000m"),
						corev1.ResourceMemory: resource.MustParse("1Gi"),
					},
					Requests: corev1.ResourceList{
						corev1.ResourceCPU:    resource.MustParse("100m"),
						corev1.ResourceMemory: resource.MustParse("256Mi"),
					},
				}
			}
		}
	}

	// Add GPU resources for data-sinker-job container if GPUEnabled is set to "yes"
	// (Delete 操作不需要 GPU，跳过)。
	if strings.EqualFold(dd.Spec.GPUEnabled, "yes") && !strings.EqualFold(operation, "Delete") {
		for i := range podSpec.Containers {
			if podSpec.Containers[i].Name == "data-sinker-job" {
				podSpec.Containers[i].Resources.Limits["nvidia.com/gpu"] = resource.MustParse("1")
				podSpec.Containers[i].Resources.Requests["nvidia.com/gpu"] = resource.MustParse("1")
				// GPU MinerU benefits from a higher memory request for scheduling/placement.
				podSpec.Containers[i].Resources.Requests[corev1.ResourceMemory] = resource.MustParse("8Gi")
			}
		}
	}

	deployment := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:            name,
			Namespace:       dd.Namespace,
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
