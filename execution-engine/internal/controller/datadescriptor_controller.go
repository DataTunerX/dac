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
	"k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"time"

	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
)

const (
	requeueAfter = 20 * time.Second
)

// DataDescriptorReconciler reconciles a DataDescriptor object
type DataDescriptorReconciler struct {
	client.Client
	Scheme  *runtime.Scheme
	Handler *handler.DataDescriptorHandler
}

// +kubebuilder:rbac:groups=dac.dac.io,resources=datadescriptors,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=dac.dac.io,resources=datadescriptors/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=dac.dac.io,resources=datadescriptors/finalizers,verbs=update
// +kubebuilder:rbac:groups=dac.dac.io,resources=dataagentcontainers,verbs=get;list;watch
// +kubebuilder:rbac:groups=core,resources=events,verbs=get;list;watch;create;patch

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
// TODO(user): Modify the Reconcile function to compare the state specified by
// the DataDescriptor object against the actual cluster state, and then
// perform operations to make the cluster state reflect the state specified by
// the user.
//
// For more details, check Reconcile and its Result here:
// - https://pkg.go.dev/sigs.k8s.io/controller-runtime@v0.21.0/pkg/reconcile
func (r *DataDescriptorReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := logf.FromContext(ctx)

	// TODO(user): your logic here

	logger.Info("Start Reconcile DataDescriptor", "namespace", req.Namespace, "name", req.Name, "type", "DataDescriptor")
	logger.Info("Reconciling DataDescriptor")

	// Fetch the DataDescriptor instance
	instance := &dacv1alpha1.DataDescriptor{}
	err := r.Client.Get(context.TODO(), req.NamespacedName, instance)
	if err != nil {
		if errors.IsNotFound(err) {
			logger.Info("DataDescriptor deleted")
			_, err = r.Handler.DoDelete(ctx, req.Namespace, req.Name)
			if err != nil {
				logger.Error(err, "DataDescriptor Handler err")
				return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
			}
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	err = r.Handler.DoAddOrUpdate(ctx, instance)
	if err != nil {
		logger.Error(err, "DataDescriptor Handler err")
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	// If there are unfinished tasks, check again later.
	if hasPendingSources(instance) {
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	return ctrl.Result{}, nil
}

func hasPendingSources(dd *dacv1alpha1.DataDescriptor) bool {

	for _, status := range dd.Status.SourceStatuses {
		// For FAILURE status, no further checks will be performed.
		if status.Phase == "FAILURE" {
			continue
		}

		// Other non-ready states need to continue checking.
		if status.Phase != "Ready" {
			return true
		}
	}
	return false
}

// SetupWithManager sets up the controller with the Manager.
func (r *DataDescriptorReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&dacv1alpha1.DataDescriptor{}).
		Named("datadescriptor").
		Complete(r)
}
