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

// dataDescriptorRepository implements domain.DataDescriptorRepository using dynamic client
type dataDescriptorRepository struct {
	client dynamic.Interface
	logger *slog.Logger
}

// NewDataDescriptorRepository creates a new data descriptor repository
func NewDataDescriptorRepository(k8sClient *k8s.Client) domain.DataDescriptorRepository {
	return &dataDescriptorRepository{
		client: k8sClient.GetDynamicClient(),
		logger: slog.Default(),
	}
}

// Create creates a new data descriptor
func (r *dataDescriptorRepository) Create(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error) {
	unst, err := r.toUnstructured(descriptor)
	if err != nil {
		return nil, fmt.Errorf("failed to convert to unstructured: %w", err)
	}

	created, err := r.client.Resource(k8s.DataDescriptorGVR).
		Namespace(descriptor.Namespace).
		Create(ctx, unst, metav1.CreateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "data descriptor", descriptor.Name)
	}

	return r.fromUnstructured(created)
}

// Get retrieves a data descriptor by namespace and name
func (r *dataDescriptorRepository) Get(ctx context.Context, namespace, name string) (*entity.DataDescriptor, error) {
	unst, err := r.client.Resource(k8s.DataDescriptorGVR).
		Namespace(namespace).
		Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, handleK8sError(err, "data descriptor", name)
	}

	return r.fromUnstructured(unst)
}

// List lists data descriptors in a namespace
func (r *dataDescriptorRepository) List(ctx context.Context, namespace string, opts domain.ListOptions) ([]*entity.DataDescriptor, error) {
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
		list, err = r.client.Resource(k8s.DataDescriptorGVR).
			List(ctx, listOpts)
	} else {
		list, err = r.client.Resource(k8s.DataDescriptorGVR).
			Namespace(namespace).
			List(ctx, listOpts)
	}

	if err != nil {
		return nil, handleK8sError(err, "data descriptor", "")
	}

	descriptors := make([]*entity.DataDescriptor, 0, len(list.Items))
	for i := range list.Items {
		descriptor, err := r.fromUnstructured(&list.Items[i])
		if err != nil {
			r.logger.Warn("failed to convert data descriptor", "name", list.Items[i].GetName(), "error", err)
			continue
		}
		descriptors = append(descriptors, descriptor)
	}

	return descriptors, nil
}

// Update updates a data descriptor
func (r *dataDescriptorRepository) Update(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error) {
	unst, err := r.toUnstructured(descriptor)
	if err != nil {
		return nil, fmt.Errorf("failed to convert to unstructured: %w", err)
	}

	updated, err := r.client.Resource(k8s.DataDescriptorGVR).
		Namespace(descriptor.Namespace).
		Update(ctx, unst, metav1.UpdateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "data descriptor", descriptor.Name)
	}

	return r.fromUnstructured(updated)
}

// UpdateStatus updates the status of a data descriptor
func (r *dataDescriptorRepository) UpdateStatus(ctx context.Context, descriptor *entity.DataDescriptor) (*entity.DataDescriptor, error) {
	unst, err := r.toUnstructured(descriptor)
	if err != nil {
		return nil, fmt.Errorf("failed to convert to unstructured: %w", err)
	}

	updated, err := r.client.Resource(k8s.DataDescriptorGVR).
		Namespace(descriptor.Namespace).
		UpdateStatus(ctx, unst, metav1.UpdateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "data descriptor status", descriptor.Name)
	}

	return r.fromUnstructured(updated)
}

// Delete deletes a data descriptor
func (r *dataDescriptorRepository) Delete(ctx context.Context, namespace, name string) error {
	err := r.client.Resource(k8s.DataDescriptorGVR).
		Namespace(namespace).
		Delete(ctx, name, metav1.DeleteOptions{})
	if err != nil {
		return handleK8sError(err, "data descriptor", name)
	}

	return nil
}

// toUnstructured converts domain entity to unstructured.Unstructured
func (r *dataDescriptorRepository) toUnstructured(descriptor *entity.DataDescriptor) (*unstructured.Unstructured, error) {
	obj := map[string]interface{}{
		"apiVersion": "dac.dac.io/v1alpha1",
		"kind":       "DataDescriptor",
		"metadata": map[string]interface{}{
			"name":      descriptor.Name,
			"namespace": descriptor.Namespace,
			"labels":    descriptor.Labels,
		},
		"spec": map[string]interface{}{
			"descriptorType": descriptor.DescriptorType,
			"sources":        r.sourcesToMap(descriptor.Sources),
		},
	}

	if len(descriptor.SourceStatuses) > 0 || len(descriptor.ConsumedBy) > 0 || descriptor.OverallPhase != "" {
		status := make(map[string]interface{})
		if len(descriptor.SourceStatuses) > 0 {
			status["sourceStatuses"] = r.sourceStatusesToMap(descriptor.SourceStatuses)
		}
		if len(descriptor.ConsumedBy) > 0 {
			status["consumedBy"] = r.consumedByToMap(descriptor.ConsumedBy)
		}
		if descriptor.OverallPhase != "" {
			status["overallPhase"] = descriptor.OverallPhase
		}
		if len(descriptor.Conditions) > 0 {
			status["conditions"] = r.conditionsToMap(descriptor.Conditions)
		}
		obj["status"] = status
	}

	return &unstructured.Unstructured{Object: obj}, nil
}

// fromUnstructured converts unstructured.Unstructured to domain entity
func (r *dataDescriptorRepository) fromUnstructured(unst *unstructured.Unstructured) (*entity.DataDescriptor, error) {
	// 直接用 JSON unmarshal，避免手动字段转换
	data, err := sonic.Marshal(unst.Object)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal unstructured: %w", err)
	}

	var k8sDesc K8sDataDescriptor
	if err := sonic.Unmarshal(data, &k8sDesc); err != nil {
		return nil, fmt.Errorf("failed to unmarshal to K8sDataDescriptor: %w", err)
	}

	// 转换为 domain entity
	descriptor := &entity.DataDescriptor{
		Name:           k8sDesc.Metadata.Name,
		Namespace:      k8sDesc.Metadata.Namespace,
		Labels:         k8sDesc.Metadata.Labels,
		DescriptorType: k8sDesc.Spec.DescriptorType,
		Sources:        k8sDesc.Spec.Sources,
		SourceStatuses: k8sDesc.Status.SourceStatuses,
		ConsumedBy:     k8sDesc.Status.ConsumedBy,
		OverallPhase:   k8sDesc.Status.OverallPhase,
		Conditions:     k8sDesc.Status.Conditions,
		CreatedAt:      k8sDesc.Metadata.CreationTimestamp.Time,
	}
	if !k8sDesc.Metadata.DeletionTimestamp.IsZero() {
		descriptor.UpdatedAt = k8sDesc.Metadata.DeletionTimestamp.Time
	} else {
		descriptor.UpdatedAt = k8sDesc.Metadata.CreationTimestamp.Time
	}

	return descriptor, nil
}

func (r *dataDescriptorRepository) sourcesToMap(sources []entity.DataSource) []interface{} {
	result := make([]interface{}, len(sources))
	for i, source := range sources {
		sourceMap := map[string]interface{}{
			"type":     source.Type,
			"name":     source.Name,
			"metadata": source.Metadata,
		}
		if source.Extract != nil {
			sourceMap["extract"] = map[string]interface{}{
				"tables": source.Extract.Tables,
				"querys": source.Extract.Querys,
			}
		}
		if source.Prompts != nil {
			sourceMap["prompts"] = map[string]interface{}{
				"prompts": map[string]string{
					"name": source.Prompts.ConfigMapName,
				},
			}
		}
		if len(source.Processing.Cleaning) > 0 {
			cleaning := make([]interface{}, len(source.Processing.Cleaning))
			for j, rule := range source.Processing.Cleaning {
				cleaning[j] = map[string]interface{}{
					"rule":   rule.Rule,
					"params": rule.Params,
				}
			}
			sourceMap["processing"] = map[string]interface{}{
				"cleaning": cleaning,
			}
		}
		if len(source.Classification) > 0 {
			sourceMap["classification"] = r.classificationsToMap(source.Classification)
		}
		result[i] = sourceMap
	}
	return result
}

func (r *dataDescriptorRepository) classificationsToMap(classifications []entity.Classification) []interface{} {
	result := make([]interface{}, len(classifications))
	for i, c := range classifications {
		result[i] = map[string]interface{}{
			"domain":      c.Domain,
			"category":    c.Category,
			"subcategory": c.Subcategory,
			"tags":        c.Tags,
		}
	}
	return result
}

func (r *dataDescriptorRepository) sourceStatusesToMap(statuses []entity.SourceStatus) []interface{} {
	result := make([]interface{}, len(statuses))
	for i, status := range statuses {
		result[i] = map[string]interface{}{
			"name":         status.Name,
			"phase":        status.Phase,
			"lastSyncTime": status.LastSyncTime.Format("2006-01-02T15:04:05Z"),
			"records":      status.Records,
			"taskID":       status.TaskID,
		}
	}
	return result
}

func (r *dataDescriptorRepository) consumedByToMap(refs []entity.ObjectReference) []interface{} {
	result := make([]interface{}, len(refs))
	for i, ref := range refs {
		result[i] = map[string]interface{}{
			"name":      ref.Name,
			"namespace": ref.Namespace,
		}
	}
	return result
}

func (r *dataDescriptorRepository) conditionsToMap(conditions []entity.Condition) []interface{} {
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
