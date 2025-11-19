package k8s

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/bytedance/sonic"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/client-go/dynamic"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/pkg/k8s"
)

// agentContainerRepository implements domain.AgentContainerRepository using dynamic client
type agentContainerRepository struct {
	client dynamic.Interface
	logger *slog.Logger
}

// NewAgentContainerRepository creates a new agent container repository
func NewAgentContainerRepository(k8sClient *k8s.Client) domain.AgentContainerRepository {
	return &agentContainerRepository{
		client: k8sClient.GetDynamicClient(),
		logger: slog.Default(),
	}
}

// Create creates a new agent container
func (r *agentContainerRepository) Create(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error) {
	unst, err := r.toUnstructured(container)
	if err != nil {
		return nil, fmt.Errorf("failed to convert to unstructured: %w", err)
	}

	created, err := r.client.Resource(k8s.DataAgentContainerGVR).
		Namespace(container.Namespace).
		Create(ctx, unst, metav1.CreateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "agent container", container.Name)
	}

	return r.fromUnstructured(created)
}

// Get retrieves an agent container by namespace and name
func (r *agentContainerRepository) Get(ctx context.Context, namespace, name string) (*entity.AgentContainer, error) {
	unst, err := r.client.Resource(k8s.DataAgentContainerGVR).
		Namespace(namespace).
		Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, handleK8sError(err, "agent container", name)
	}

	return r.fromUnstructured(unst)
}

// List lists agent containers in a namespace
func (r *agentContainerRepository) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.AgentContainer, error) {
	listOpts := metav1.ListOptions{
		LabelSelector: opts.LabelSelector,
		FieldSelector: opts.FieldSelector,
		Limit:         opts.Limit,
		Continue:      opts.Continue,
	}

	// If AllNamespaces is true, list across all namespaces (ignore namespace parameter)
	var list *unstructured.UnstructuredList
	var err error
	if opts.AllNamespaces {
		list, err = r.client.Resource(k8s.DataAgentContainerGVR).
			List(ctx, listOpts)
	} else {
		list, err = r.client.Resource(k8s.DataAgentContainerGVR).
			Namespace(namespace).
			List(ctx, listOpts)
	}

	if err != nil {
		return nil, handleK8sError(err, "agent container", "")
	}

	containers := make([]*entity.AgentContainer, 0, len(list.Items))
	for i := range list.Items {
		container, err := r.fromUnstructured(&list.Items[i])
		if err != nil {
			r.logger.Warn("failed to convert agent container", "name", list.Items[i].GetName(), "error", err)
			continue
		}
		containers = append(containers, container)
	}

	return containers, nil
}

// Update updates an agent container
func (r *agentContainerRepository) Update(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error) {
	unst, err := r.toUnstructured(container)
	if err != nil {
		return nil, fmt.Errorf("failed to convert to unstructured: %w", err)
	}

	updated, err := r.client.Resource(k8s.DataAgentContainerGVR).
		Namespace(container.Namespace).
		Update(ctx, unst, metav1.UpdateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "agent container", container.Name)
	}

	return r.fromUnstructured(updated)
}

// UpdateStatus updates the status of an agent container
func (r *agentContainerRepository) UpdateStatus(ctx context.Context, container *entity.AgentContainer) (*entity.AgentContainer, error) {
	unst, err := r.toUnstructured(container)
	if err != nil {
		return nil, fmt.Errorf("failed to convert to unstructured: %w", err)
	}

	updated, err := r.client.Resource(k8s.DataAgentContainerGVR).
		Namespace(container.Namespace).
		UpdateStatus(ctx, unst, metav1.UpdateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "agent container status", container.Name)
	}

	return r.fromUnstructured(updated)
}

// Delete deletes an agent container
func (r *agentContainerRepository) Delete(ctx context.Context, namespace, name string) error {
	err := r.client.Resource(k8s.DataAgentContainerGVR).
		Namespace(namespace).
		Delete(ctx, name, metav1.DeleteOptions{})
	if err != nil {
		return handleK8sError(err, "agent container", name)
	}

	return nil
}

// toUnstructured converts domain entity to unstructured.Unstructured
func (r *agentContainerRepository) toUnstructured(container *entity.AgentContainer) (*unstructured.Unstructured, error) {
	obj := map[string]interface{}{
		"apiVersion": "dac.dac.io/v1alpha1",
		"kind":       "DataAgentContainer",
		"metadata": map[string]interface{}{
			"name":      container.Name,
			"namespace": container.Namespace,
			"labels":    container.Labels,
		},
		"spec": map[string]interface{}{
			"dataPolicy": map[string]interface{}{
				"sourceNameSelector": container.DataPolicy.SourceNameSelector,
			},
			"agentCard": map[string]interface{}{
				"name":        container.AgentCard.Name,
				"description": container.AgentCard.Description,
				"skills":      r.skillsToMap(container.AgentCard.Skills),
			},
			"model": map[string]interface{}{
				"embedding":  container.Model.Embedding,
				"expertLLM":  container.Model.ExpertLLM,
				"plannerLLM": container.Model.PlannerLLM,
			},
			"expertAgentMaxSteps": container.ExpertAgentMaxSteps,
		},
	}

	if len(container.ActiveDataDescriptors) > 0 || container.Endpoint != nil || len(container.Conditions) > 0 {
		status := make(map[string]interface{})
		if len(container.ActiveDataDescriptors) > 0 {
			status["activeDataDescriptors"] = r.descriptorsToMap(container.ActiveDataDescriptors)
		}
		if container.Endpoint != nil {
			status["endpoint"] = map[string]interface{}{
				"address":  container.Endpoint.Address,
				"port":     container.Endpoint.Port,
				"protocol": container.Endpoint.Protocol,
			}
		}
		if len(container.Conditions) > 0 {
			status["conditions"] = r.conditionsToMap(container.Conditions)
		}
		obj["status"] = status
	}

	return &unstructured.Unstructured{Object: obj}, nil
}

// fromUnstructured converts unstructured.Unstructured to domain entity
func (r *agentContainerRepository) fromUnstructured(unst *unstructured.Unstructured) (*entity.AgentContainer, error) {
	// 直接用 JSON unmarshal，避免手动字段转换
	data, err := sonic.Marshal(unst.Object)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal unstructured: %w", err)
	}

	var k8sContainer K8sAgentContainer
	if err := sonic.Unmarshal(data, &k8sContainer); err != nil {
		return nil, fmt.Errorf("failed to unmarshal to K8sAgentContainer: %w", err)
	}

	// 转换为 domain entity
	container := &entity.AgentContainer{
		Name:                  k8sContainer.Metadata.Name,
		Namespace:             k8sContainer.Metadata.Namespace,
		Labels:                k8sContainer.Metadata.Labels,
		DataPolicy:            k8sContainer.Spec.DataPolicy,
		AgentCard:             k8sContainer.Spec.AgentCard,
		Model:                 k8sContainer.Spec.Model,
		ExpertAgentMaxSteps:   k8sContainer.Spec.ExpertAgentMaxSteps,
		ActiveDataDescriptors: k8sContainer.Status.ActiveDataDescriptors,
		Endpoint:              k8sContainer.Status.Endpoint,
		Conditions:            k8sContainer.Status.Conditions,
		CreatedAt:             k8sContainer.Metadata.CreationTimestamp.Time,
	}
	if !k8sContainer.Metadata.DeletionTimestamp.IsZero() {
		container.UpdatedAt = k8sContainer.Metadata.DeletionTimestamp.Time
	} else {
		container.UpdatedAt = k8sContainer.Metadata.CreationTimestamp.Time
	}

	return container, nil
}

func (r *agentContainerRepository) skillsToMap(skills []entity.AgentSkill) []interface{} {
	result := make([]interface{}, len(skills))
	for i, skill := range skills {
		result[i] = map[string]interface{}{
			"id":          skill.ID,
			"name":        skill.Name,
			"description": skill.Description,
			"tags":        skill.Tags,
			"examples":    skill.Examples,
		}
	}
	return result
}

func (r *agentContainerRepository) descriptorsToMap(descriptors []entity.ActiveDataDescriptor) []interface{} {
	result := make([]interface{}, len(descriptors))
	for i, d := range descriptors {
		result[i] = map[string]interface{}{
			"name":       d.Name,
			"namespace":  d.Namespace,
			"lastSynced": d.LastSynced,
		}
	}
	return result
}

func (r *agentContainerRepository) conditionsToMap(conditions []entity.Condition) []interface{} {
	result := make([]interface{}, len(conditions))
	for i, c := range conditions {
		result[i] = map[string]interface{}{
			"type":               c.Type,
			"status":             c.Status,
			"lastTransitionTime": c.LastTransitionTime.Format("2006-01-02T15:04:05Z"),
			"reason":             c.Reason,
			"message":            c.Message,
		}
	}
	return result
}
