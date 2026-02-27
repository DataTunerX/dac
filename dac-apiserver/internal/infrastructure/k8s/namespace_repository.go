package k8s

import (
	"context"
	"sort"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	pkgk8s "github.com/lvyanru/dac-apiserver/pkg/k8s"
)

type namespaceRepository struct {
	clientset *kubernetes.Clientset
}

func NewNamespaceRepository(k8sClient *pkgk8s.Client) domain.NamespaceRepository {
	return &namespaceRepository{clientset: k8sClient.GetClientset()}
}

func (r *namespaceRepository) List(ctx context.Context) ([]*entity.Namespace, error) {
	list, err := r.clientset.CoreV1().Namespaces().List(ctx, metav1.ListOptions{})
	if err != nil {
		return nil, handleK8sError(err, "Namespace", "")
	}

	items := make([]*entity.Namespace, 0, len(list.Items))
	for i := range list.Items {
		ns := &list.Items[i]
		items = append(items, &entity.Namespace{
			Name:      ns.Name,
			Labels:    ns.Labels,
			CreatedAt: ns.CreationTimestamp.Time,
		})
	}

	sort.Slice(items, func(i, j int) bool { return items[i].Name < items[j].Name })
	return items, nil
}

var _ domain.NamespaceRepository = (*namespaceRepository)(nil)

