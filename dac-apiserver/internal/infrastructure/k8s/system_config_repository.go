package k8s

import (
	"context"
	"fmt"
	"sort"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	pkgk8s "github.com/lvyanru/dac-apiserver/pkg/k8s"
)

type systemConfigRepository struct {
	clientset *kubernetes.Clientset
	namespace string
}

func NewSystemConfigRepository(k8sClient *pkgk8s.Client) domain.SystemConfigRepository {
	return &systemConfigRepository{
		clientset: k8sClient.GetClientset(),
		namespace: domain.SystemConfigNamespace,
	}
}

func (r *systemConfigRepository) Get(ctx context.Context, name string) (*domain.RawSystemConfigMap, error) {
	obj, err := r.clientset.CoreV1().ConfigMaps(r.namespace).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, handleK8sError(err, "SystemConfiguration", name)
	}
	return mapRawSystemConfig(obj), nil
}

func (r *systemConfigRepository) ListArchives(ctx context.Context, sourceName string) ([]*domain.RawSystemConfigMap, error) {
	labelSel := fmt.Sprintf("%s=true,%s=%s",
		domain.SystemConfigArchiveLabel, domain.SystemConfigSourceLabel, sourceName)
	list, err := r.clientset.CoreV1().ConfigMaps(r.namespace).List(ctx, metav1.ListOptions{LabelSelector: labelSel})
	if err != nil {
		return nil, handleK8sError(err, "SystemConfiguration", sourceName)
	}

	items := make([]*domain.RawSystemConfigMap, 0, len(list.Items))
	for i := range list.Items {
		items = append(items, mapRawSystemConfig(&list.Items[i]))
	}

	sort.Slice(items, func(i, j int) bool {
		vi := items[i].Labels[domain.SystemConfigVersionLabel]
		vj := items[j].Labels[domain.SystemConfigVersionLabel]
		if vi != vj {
			return vi > vj
		}
		return items[i].Name > items[j].Name
	})

	return items, nil
}

func (r *systemConfigRepository) Create(ctx context.Context, cm *domain.RawSystemConfigMap) (*domain.RawSystemConfigMap, error) {
	obj := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      cm.Name,
			Namespace: r.namespace,
			Labels:    cloneStringMap(cm.Labels),
		},
		Data: cloneStringMap(cm.Data),
	}

	created, err := r.clientset.CoreV1().ConfigMaps(r.namespace).Create(ctx, obj, metav1.CreateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "SystemConfiguration", cm.Name)
	}
	return mapRawSystemConfig(created), nil
}

func (r *systemConfigRepository) Replace(ctx context.Context, cm *domain.RawSystemConfigMap) (*domain.RawSystemConfigMap, error) {
	existing, err := r.clientset.CoreV1().ConfigMaps(r.namespace).Get(ctx, cm.Name, metav1.GetOptions{})
	if err != nil {
		return nil, handleK8sError(err, "SystemConfiguration", cm.Name)
	}

	if cm.ResourceVersion != "" && existing.ResourceVersion != cm.ResourceVersion {
		return nil, domain.NewConflictError(
			fmt.Sprintf("SystemConfiguration '%s' has been modified", cm.Name),
		)
	}

	existing.Labels = cloneStringMap(cm.Labels)
	existing.Data = cloneStringMap(cm.Data)

	updated, err := r.clientset.CoreV1().ConfigMaps(r.namespace).Update(ctx, existing, metav1.UpdateOptions{})
	if err != nil {
		return nil, handleK8sError(err, "SystemConfiguration", cm.Name)
	}
	return mapRawSystemConfig(updated), nil
}

func (r *systemConfigRepository) Delete(ctx context.Context, name, resourceVersion string) error {
	opts := metav1.DeleteOptions{}
	if resourceVersion != "" {
		rv := resourceVersion
		opts.Preconditions = &metav1.Preconditions{
			ResourceVersion: &rv,
		}
	}
	if err := r.clientset.CoreV1().ConfigMaps(r.namespace).Delete(ctx, name, opts); err != nil {
		return handleK8sError(err, "SystemConfiguration", name)
	}
	return nil
}

func mapRawSystemConfig(cm *corev1.ConfigMap) *domain.RawSystemConfigMap {
	return &domain.RawSystemConfigMap{
		Name:              cm.Name,
		Namespace:         cm.Namespace,
		Labels:            cloneStringMap(cm.Labels),
		Data:              cloneStringMap(cm.Data),
		ResourceVersion:   cm.ResourceVersion,
		CreationTimestamp: cm.CreationTimestamp.Time,
	}
}

var _ domain.SystemConfigRepository = (*systemConfigRepository)(nil)
