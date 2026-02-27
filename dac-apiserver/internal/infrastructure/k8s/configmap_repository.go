package k8s

import (
	"context"
	"fmt"
	"sort"
	"strings"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	pkgk8s "github.com/lvyanru/dac-apiserver/pkg/k8s"
)

const (
	configMapTypeLabelKey = "dac.io/config-type"
	managedByLabelKey     = "app.kubernetes.io/managed-by"
	managedByLabelValue   = "dac-apiserver"
)

type configMapRepository struct {
	clientset *kubernetes.Clientset
}

func NewConfigMapRepository(k8sClient *pkgk8s.Client) domain.ConfigMapRepository {
	return &configMapRepository{clientset: k8sClient.GetClientset()}
}

func (r *configMapRepository) Create(ctx context.Context, cm *entity.ConfigMap, t domain.ConfigMapType) (*entity.ConfigMap, error) {
	obj := &corev1.ConfigMap{}
	obj.Name = cm.Name
	obj.Namespace = cm.Namespace
	obj.Labels = cloneStringMap(cm.Labels)
	if t != "" {
		if obj.Labels == nil {
			obj.Labels = map[string]string{}
		}
		obj.Labels[configMapTypeLabelKey] = string(t)
		obj.Labels[managedByLabelKey] = managedByLabelValue
	}
	obj.Data = cloneStringMap(cm.Data)

	created, err := r.clientset.CoreV1().ConfigMaps(cm.Namespace).Create(ctx, obj, metav1.CreateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "ConfigMap", cm.Name)
	}
	return mapK8sConfigMapToEntity(created), nil
}

func (r *configMapRepository) Get(ctx context.Context, namespace, name string) (*entity.ConfigMap, error) {
	obj, err := r.clientset.CoreV1().ConfigMaps(namespace).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, handleK8sError(err, "ConfigMap", name)
	}
	return mapK8sConfigMapToEntity(obj), nil
}

func (r *configMapRepository) List(ctx context.Context, namespace string, opts domain.ConfigMapListOptions) ([]*entity.ConfigMap, error) {
	labelSel := ""
	if opts.Type != "" {
		labelSel = fmt.Sprintf("%s=%s,%s=%s", configMapTypeLabelKey, string(opts.Type), managedByLabelKey, managedByLabelValue)
	} else {
		// Even if no type selected, we should filter by managed-by?
		// To match user intent "is these two labels", probably yes if they want to list DAC configmaps.
		// However, standard List usually just lists everything unless filtered.
		// Given the user query, let's play safe and only enforce managed-by if Type is present (implicit "DAC ConfigMap").
		// If user wants to see ALL configmaps, they might not pass type.
		// But "ConfigMap Management" page in frontend always passes type=llm or prompts (defaults to llm).
		// So enforcing it here is safe for the specific use case.
		// But let's check if opts.Type is empty.
	}
	
	// If type is empty, we don't enforce managed-by to allow listing generic configmaps if needed?
	// But let's stick to the previous logic structure first, just updating the key.
	// Wait, if I change the key, I MUST update the selector.
	
	if opts.Type != "" {
		labelSel = fmt.Sprintf("%s=%s", configMapTypeLabelKey, string(opts.Type))
		// Should we also enforce managed-by? The user said "is these two labels".
		// It's safer to enforce both to avoid picking up random configmaps that happen to have the type label (unlikely but possible).
		// But the most critical part is the KEY change.
		labelSel = fmt.Sprintf("%s=%s,%s=%s", configMapTypeLabelKey, string(opts.Type), managedByLabelKey, managedByLabelValue)
	}
	if strings.TrimSpace(opts.LabelSelector) != "" {
		if labelSel != "" {
			labelSel += ","
		}
		labelSel += strings.TrimSpace(opts.LabelSelector)
	}

	list, err := r.clientset.CoreV1().ConfigMaps(namespace).List(ctx, metav1.ListOptions{LabelSelector: labelSel})
	if err != nil {
		return nil, handleK8sError(err, "ConfigMap", namespace)
	}

	items := make([]*entity.ConfigMap, 0, len(list.Items))
	for i := range list.Items {
		items = append(items, mapK8sConfigMapToEntity(&list.Items[i]))
	}

	// Stable sort by name for deterministic pagination/slicing in handlers.
	sort.Slice(items, func(i, j int) bool {
		return items[i].Name < items[j].Name
	})

	return items, nil
}

func (r *configMapRepository) Update(ctx context.Context, cm *entity.ConfigMap, t domain.ConfigMapType) (*entity.ConfigMap, error) {
	existing, err := r.clientset.CoreV1().ConfigMaps(cm.Namespace).Get(ctx, cm.Name, metav1.GetOptions{})
	if err != nil {
		return nil, handleK8sError(err, "ConfigMap", cm.Name)
	}

	existing.Labels = cloneStringMap(cm.Labels)
	if t != "" {
		if existing.Labels == nil {
			existing.Labels = map[string]string{}
		}
		existing.Labels[configMapTypeLabelKey] = string(t)
		existing.Labels[managedByLabelKey] = managedByLabelValue
	}
	existing.Data = cloneStringMap(cm.Data)

	updated, err := r.clientset.CoreV1().ConfigMaps(cm.Namespace).Update(ctx, existing, metav1.UpdateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "ConfigMap", cm.Name)
	}
	return mapK8sConfigMapToEntity(updated), nil
}

func (r *configMapRepository) Delete(ctx context.Context, namespace, name string) error {
	if err := r.clientset.CoreV1().ConfigMaps(namespace).Delete(ctx, name, metav1.DeleteOptions{}); err != nil {
		return handleK8sError(err, "ConfigMap", name)
	}
	return nil
}

func mapK8sConfigMapToEntity(cm *corev1.ConfigMap) *entity.ConfigMap {
	return &entity.ConfigMap{
		Name:      cm.Name,
		Namespace: cm.Namespace,
		Labels:    cloneStringMap(cm.Labels),
		Data:      cloneStringMap(cm.Data),
		CreatedAt: cm.CreationTimestamp.Time,
	}
}

func cloneStringMap(in map[string]string) map[string]string {
	if in == nil {
		return nil
	}
	out := make(map[string]string, len(in))
	for k, v := range in {
		out[k] = v
	}
	return out
}

var _ domain.ConfigMapRepository = (*configMapRepository)(nil)

