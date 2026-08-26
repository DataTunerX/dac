package k8s

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// Client Kubernetes client封装
type Client struct {
	// Kubernetes 标准 clientset
	clientset *kubernetes.Clientset
	// Dynamic client for CRDs
	dynamicClient dynamic.Interface
	// REST 配置
	config *rest.Config

	gpuCacheMu      sync.Mutex
	gpuCache        *GPUAvailability
	gpuCacheExpires time.Time
}

// GroupVersionResource definitions for DAC CRDs
var (
	DataAgentContainerGVR = schema.GroupVersionResource{
		Group:    "dac.dac.io",
		Version:  "v1alpha1",
		Resource: "dataagentcontainers",
	}

	DataDescriptorGVR = schema.GroupVersionResource{
		Group:    "dac.dac.io",
		Version:  "v1alpha1",
		Resource: "datadescriptors",
	}
)

const NVIDIAResourceKey corev1.ResourceName = "nvidia.com/gpu"

// GPUAvailability describes whether the current Kubernetes cluster can schedule NVIDIA GPU workloads.
type GPUAvailability struct {
	Available   bool
	NodeCount   int
	TotalGPUs   int64
	ResourceKey string
}

// NewClient createof Kubernetes client
// It prefers the in-cluster configuration (when running inside a Kubernetes
// pod with a ServiceAccount). When that is unavailable — e.g. running the
// binary as a container outside the cluster — it falls back to the standard
// kubeconfig lookup chain (KUBECONFIG env, then ~/.kube/config), so the same
// image can be used for local development/testing and in-cluster deployment.
func NewClient() (*Client, error) {
	restConfig, err := newRESTConfig()
	if err != nil {
		return nil, fmt.Errorf("failed to build kubernetes config: %w", err)
	}

	// Set default QPS and Burst
	restConfig.QPS = 50
	restConfig.Burst = 100

	// create standard clientset
	clientset, err := kubernetes.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to create kubernetes clientset: %w", err)
	}

	// create dynamic client
	dynamicClient, err := dynamic.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("failed to create dynamic client: %w", err)
	}

	slog.Info("kubernetes client created successfully",
		"qps", restConfig.QPS,
		"burst", restConfig.Burst,
		"host", restConfig.Host,
	)

	return &Client{
		clientset:     clientset,
		dynamicClient: dynamicClient,
		config:        restConfig,
	}, nil
}

// newRESTConfig builds a *rest.Config, preferring the in-cluster ServiceAccount
// configuration and falling back to the kubeconfig loading rules otherwise.
func newRESTConfig() (*rest.Config, error) {
	if cfg, err := rest.InClusterConfig(); err == nil {
		return cfg, nil
	}

	rules := clientcmd.NewDefaultClientConfigLoadingRules()
	overrides := &clientcmd.ConfigOverrides{}
	cfg, err := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(rules, overrides).ClientConfig()
	if err != nil {
		return nil, fmt.Errorf("in-cluster config unavailable and no kubeconfig found: %w", err)
	}
	return cfg, nil
}

// GetClientset get Kubernetes 标准 clientset
func (c *Client) GetClientset() *kubernetes.Clientset {
	return c.clientset
}

// GetDynamicClient get dynamic client
func (c *Client) GetDynamicClient() dynamic.Interface {
	return c.dynamicClient
}

// GetConfig get REST 配置
func (c *Client) GetConfig() *rest.Config {
	return c.config
}

// HealthCheck 检查 Kubernetes 连接健康状态
func (c *Client) HealthCheck(ctx context.Context) error {
	_, err := c.clientset.Discovery().ServerVersion()
	if err != nil {
		return fmt.Errorf("kubernetes health check failed: %w", err)
	}
	return nil
}

func (c *Client) GPUAvailability(ctx context.Context) (*GPUAvailability, error) {
	c.gpuCacheMu.Lock()
	if c.gpuCache != nil && time.Now().Before(c.gpuCacheExpires) {
		cached := *c.gpuCache
		c.gpuCacheMu.Unlock()
		return &cached, nil
	}
	c.gpuCacheMu.Unlock()

	nodes, err := c.clientset.CoreV1().Nodes().List(ctx, metav1.ListOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to list kubernetes nodes: %w", err)
	}

	var total int64
	gpuNodes := 0
	for i := range nodes.Items {
		qty, ok := nodes.Items[i].Status.Allocatable[NVIDIAResourceKey]
		if !ok {
			continue
		}
		count := qty.Value()
		if count <= 0 {
			continue
		}
		gpuNodes++
		total += count
	}

	availability := &GPUAvailability{
		Available:   total > 0,
		NodeCount:   gpuNodes,
		TotalGPUs:   total,
		ResourceKey: string(NVIDIAResourceKey),
	}

	c.gpuCacheMu.Lock()
	c.gpuCache = availability
	c.gpuCacheExpires = time.Now().Add(30 * time.Second)
	c.gpuCacheMu.Unlock()

	return availability, nil
}
