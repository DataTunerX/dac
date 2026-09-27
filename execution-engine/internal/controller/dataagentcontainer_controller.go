/*
Copyright 2025.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"
	"github.com/DataTunerX/dac/execution-engine/internal/handler"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	crhandler "sigs.k8s.io/controller-runtime/pkg/handler"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"
	"time"

	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
)

// dac-configuration (ns dac) carries the cluster-wide default image tags
// (skill-agent-image, orchestrator-agent-image, …) that GenerateSkillDataAgentContainerDeployment
// and friends read fresh on every reconcile. Bumping it (e.g. via `helm upgrade`) does not, on its
// own, touch any already-running DataAgentContainer — the object's own spec never changes, so no
// Update event fires for it. The Watches() below closes that gap: a change to this ConfigMap
// requeues every DataAgentContainer so already-running agents pick up the new image instead of
// only agents created after the bump.
const (
	dacConfigConfigMapName      = "dac-configuration"
	dacConfigConfigMapNamespace = "dac"
)

// DataAgentContainerReconciler reconciles a DataAgentContainer object
type DataAgentContainerReconciler struct {
	client.Client
	Scheme  *runtime.Scheme
	Handler *handler.DataAgentContainerHandler
}

// +kubebuilder:rbac:groups=dac.dac.io,resources=dataagentcontainers,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=dac.dac.io,resources=dataagentcontainers/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=dac.dac.io,resources=dataagentcontainers/finalizers,verbs=update
// +kubebuilder:rbac:groups=dac.dac.io,resources=datadescriptors,verbs=get;list;watch
// +kubebuilder:rbac:groups=core,resources=events,verbs=get;list;watch;create;patch
// +kubebuilder:rbac:groups=core,resources=pods,verbs=get;list;watch;delete;deletecollection
// +kubebuilder:rbac:groups=core,resources=persistentvolumeclaims,verbs=get;list;watch;delete;deletecollection
// +kubebuilder:rbac:groups=core,resources=configmaps,verbs=get;list;watch;create;update;patch;delete;deletecollection
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete;deletecollection
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete;deletecollection
// +kubebuilder:rbac:groups=apps,resources=replicasets,verbs=get;list;watch;create;update;patch;delete;deletecollection
// +kubebuilder:rbac:groups=apps,resources=deployments/finalizers,verbs=update;delete;deletecollection
// +kubebuilder:rbac:groups=rbac.authorization.k8s.io,resources=roles,verbs=get;list;watch;create;update;patch;delete;deletecollection
// +kubebuilder:rbac:groups=rbac.authorization.k8s.io,resources=rolebindings,verbs=get;list;watch;create;update;patch;delete;deletecollection

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
// TODO(user): Modify the Reconcile function to compare the state specified by
// the DataAgentContainer object against the actual cluster state, and then
// perform operations to make the cluster state reflect the state specified by
// the user.
//
// For more details, check Reconcile and its Result here:
// - https://pkg.go.dev/sigs.k8s.io/controller-runtime@v0.21.0/pkg/reconcile
func (r *DataAgentContainerReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := logf.FromContext(ctx)

	// TODO(user): your logic here

	logger.Info("Start Reconcile DataAgentContainer", "namespace", req.Namespace, "name", req.Name, "type", "DataAgentContainer")
	logger.Info("Reconciling DataDescriptor")

	// Fetch the DataAgentContainer instance
	instance := &dacv1alpha1.DataAgentContainer{}
	err := r.Client.Get(context.TODO(), req.NamespacedName, instance)
	if err != nil {
		if errors.IsNotFound(err) {
			logger.Info("DataAgentContainer deleted", "namespace", req.Namespace, "name", req.Name, "type", "DataAgentContainer")
			return ctrl.Result{}, nil
		}
		// Error reading the object - requeue the request.
		return ctrl.Result{}, err
	}

	err = r.Handler.Do(ctx, instance)
	if err != nil {
		logger.Error(err, "DataAgentContainer Handler err")
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	return ctrl.Result{}, nil
}

// enqueueAllDataAgentContainers maps a dac-configuration change to a reconcile
// request for every DataAgentContainer in the cluster, so image bumps (and any
// other dac-configuration field the generator reads) roll out to already-running
// agents instead of only affecting agents created after the change.
func (r *DataAgentContainerReconciler) enqueueAllDataAgentContainers(ctx context.Context, _ client.Object) []reconcile.Request {
	logger := logf.FromContext(ctx)

	var list dacv1alpha1.DataAgentContainerList
	if err := r.Client.List(ctx, &list); err != nil {
		logger.Error(err, "Failed to list DataAgentContainers for dac-configuration watch")
		return nil
	}

	requests := make([]reconcile.Request, 0, len(list.Items))
	for _, item := range list.Items {
		requests = append(requests, reconcile.Request{
			NamespacedName: types.NamespacedName{Namespace: item.Namespace, Name: item.Name},
		})
	}
	logger.Info("dac-configuration changed, requeueing all DataAgentContainers", "count", len(requests))
	return requests
}

// SetupWithManager sets up the controller with the Manager.
func (r *DataAgentContainerReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&dacv1alpha1.DataAgentContainer{}).
		Watches(
			&corev1.ConfigMap{},
			crhandler.EnqueueRequestsFromMapFunc(r.enqueueAllDataAgentContainers),
			builder.WithPredicates(predicate.NewPredicateFuncs(func(obj client.Object) bool {
				return obj.GetNamespace() == dacConfigConfigMapNamespace && obj.GetName() == dacConfigConfigMapName
			})),
		).
		Named("dataagentcontainer").
		Complete(r)
}
