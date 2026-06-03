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
	"errors"

	"github.com/DataTunerX/dac/execution-engine/internal/handler"
	"github.com/go-logr/logr"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"time"

	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
)

const (
	requeueAfter                 = 20 * time.Second
	dataDescriptorFinalizer      = "datadescriptor.dac.dac.io/finalizer"
	deletionJobStartedAnnotation = "dac.dac.io/deletion-job-started"
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
// +kubebuilder:rbac:groups=dac.dac.io,resources=dataagentcontainers,verbs=get;list;watch;create;update;delete
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
		if apierrors.IsNotFound(err) {
			logger.Info("DataDescriptor not found, may have been fully deleted")
			// Object already deleted, check if there are orphaned resources to clean up
			// This can happen if the object was deleted without finalizer or if finalizer was removed
			minimalInstance := &dacv1alpha1.DataDescriptor{
				ObjectMeta: metav1.ObjectMeta{
					Name:      req.Name,
					Namespace: req.Namespace,
				},
			}
			if r.Handler.HasResourcesToCleanup(ctx, minimalInstance) {
				logger.Info("Orphaned resources found, cleaning up")
				r.Handler.CleanupResources(ctx, minimalInstance)
				return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
			}
			// No resources to clean up, deletion is complete
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	// If DeletionTimestamp is set, handle deletion
	if instance.DeletionTimestamp != nil {
		logger.Info("DataDescriptor is being deleted, starting deletion process")

		// Check if finalizer exists
		if controllerutil.ContainsFinalizer(instance, dataDescriptorFinalizer) {
			resourcesExist := r.Handler.HasResourcesToCleanup(ctx, instance)

			if resourcesExist {
				// Resources exist: check if it's a Delete operation or AddOrUpdate operation
				operationType := r.Handler.GetCurrentOperationType(ctx, instance)
				logger.Info("Existing resources found during deletion", "operationType", operationType)

				if operationType == "AddOrUpdate" {
					// If existing deployment is from AddOrUpdate operation, we need to clean it up
					// and start the delete job instead of waiting for AddOrUpdate to complete
					logger.Info("Existing deployment is from AddOrUpdate, cleaning up and starting delete job")
					r.Handler.CleanupResources(ctx, instance)
					// Mark deletion job as started and call DoDelete
					if instance.Annotations == nil {
						instance.Annotations = make(map[string]string)
					}
					if instance.Annotations[deletionJobStartedAnnotation] != "true" {
						instance.Annotations[deletionJobStartedAnnotation] = "true"
						if err := r.Client.Update(ctx, instance); err != nil {
							if apierrors.IsNotFound(err) {
								return ctrl.Result{}, nil
							}
							logger.Error(err, "Failed to set deletion-job-started annotation")
							return ctrl.Result{RequeueAfter: 10 * time.Second}, err
						}
						_, err = r.Handler.DoDelete(ctx, req.Namespace, req.Name)
						if err != nil {
							if errors.Is(err, handler.ErrRequeueNeeded) {
								logger.Info("Normal DAC replacement pending after delete job, requeueing")
								return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
							}
							logger.Error(err, "DataDescriptor Handler err during deletion after cleanup")
						}
					}
					return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
				}

				// It's a Delete operation, check deletion job status and cleanup if done.
				r.Handler.CheckDeletionJobStatusAndCleanup(ctx, req.Namespace, req.Name)
				// Re-fetch to get latest state after possible cleanup
				if err := r.Client.Get(ctx, req.NamespacedName, instance); err != nil {
					if apierrors.IsNotFound(err) {
						minimalInstance := &dacv1alpha1.DataDescriptor{
							ObjectMeta: metav1.ObjectMeta{Name: req.Name, Namespace: req.Namespace},
						}
						if r.Handler.HasResourcesToCleanup(ctx, minimalInstance) {
							r.Handler.CleanupResources(ctx, minimalInstance)
							return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
						}
						return ctrl.Result{}, nil
					}
					return ctrl.Result{RequeueAfter: 10 * time.Second}, err
				}
				if r.Handler.HasResourcesToCleanup(ctx, instance) {
					return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
				}
				// Fall through to remove finalizer
			} else {
				// No resources: either we haven't started the deletion job yet, or we/user already cleaned up.
				// If we already started (annotation set), do not call DoDelete to avoid recreating after manual delete.
				if instance.Annotations != nil && instance.Annotations[deletionJobStartedAnnotation] == "true" {
					logger.Info("Deletion job was already started, resources gone (cleaned up or manually deleted), removing finalizer")
					// Fall through to remove finalizer
				} else {
					// First time: mark that we started the deletion job, then create resources and run job
					if instance.Annotations == nil {
						instance.Annotations = make(map[string]string)
					}
					instance.Annotations[deletionJobStartedAnnotation] = "true"
					if err := r.Client.Update(ctx, instance); err != nil {
						if apierrors.IsNotFound(err) {
							return ctrl.Result{}, nil
						}
						logger.Error(err, "Failed to set deletion-job-started annotation")
						return ctrl.Result{RequeueAfter: 10 * time.Second}, err
					}
					_, err = r.Handler.DoDelete(ctx, req.Namespace, req.Name)
					if err != nil {
						if errors.Is(err, handler.ErrRequeueNeeded) {
							logger.Info("Normal DAC replacement pending after delete job, requeueing")
							return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
						}
						logger.Error(err, "DataDescriptor Handler err during deletion")
					}
					// Re-fetch and decide: requeue if resources still exist, else remove finalizer
					if err := r.Client.Get(ctx, req.NamespacedName, instance); err != nil {
						if apierrors.IsNotFound(err) {
							return ctrl.Result{}, nil
						}
						return ctrl.Result{RequeueAfter: 10 * time.Second}, err
					}
					if r.Handler.HasResourcesToCleanup(ctx, instance) {
						return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
					}
					// Fall through to remove finalizer
				}
			}

			// All resources cleaned up (or already gone). Sync normal DAC for affected
			// groups before removing the finalizer (reads dac.dac.io/semantic-group-ids).
			if err := r.Client.Get(ctx, req.NamespacedName, instance); err != nil {
				if apierrors.IsNotFound(err) {
					return ctrl.Result{}, nil
				}
				logger.Error(err, "Failed to re-fetch DataDescriptor before normal DAC sync after delete")
				return ctrl.Result{RequeueAfter: 10 * time.Second}, err
			}
			semanticGroupIDsRaw := ""
			if instance.Annotations != nil {
				semanticGroupIDsRaw = instance.Annotations["dac.dac.io/semantic-group-ids"]
			}
			logger.Info("Invoking EnsureNormalDACAfterDelete before finalizer removal",
				"feature", "delete_normal_dac_sync",
				"step", "controller_invoke",
				"semanticGroupIDsAnnotation", semanticGroupIDsRaw,
				"deletionJobStarted", instance.Annotations != nil && instance.Annotations[deletionJobStartedAnnotation] == "true")
			needsNormalDACRequeue, err := r.Handler.EnsureNormalDACAfterDelete(ctx, instance.Namespace, instance.Name)
			if err != nil {
				logger.Error(err, "Failed to sync normal DAC after delete",
					"feature", "delete_normal_dac_sync",
					"step", "controller_error")
			}
			if needsNormalDACRequeue {
				logger.Info("Normal DAC blue-green in progress after delete, delaying finalizer removal",
					"feature", "delete_normal_dac_sync",
					"step", "controller_delay_finalizer")
				return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
			}

			return r.removeDataDescriptorFinalizer(ctx, req.NamespacedName, logger)
		} else {
			// Finalizer not present, but DeletionTimestamp is set
			logger.Info("DeletionTimestamp set but no finalizer, checking for orphaned resources")
			if r.Handler.HasResourcesToCleanup(ctx, instance) {
				logger.Info("Orphaned resources found, cleaning up")
				r.Handler.CleanupResources(ctx, instance)
				return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
			}
		}
		return ctrl.Result{}, nil
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(instance, dataDescriptorFinalizer) {
		logger.Info("Adding finalizer to DataDescriptor")
		controllerutil.AddFinalizer(instance, dataDescriptorFinalizer)
		if err := r.Client.Update(ctx, instance); err != nil {
			logger.Error(err, "Failed to add finalizer")
			return ctrl.Result{RequeueAfter: 10 * time.Second}, err
		}
		// Requeue to continue with normal reconciliation
		return ctrl.Result{Requeue: true}, nil
	}

	err = r.Handler.DoAddOrUpdate(ctx, instance)
	if err != nil {
		if errors.Is(err, handler.ErrRequeueNeeded) {
			logger.Info("Normal DAC replacement pending, requeueing in 30s")
			return ctrl.Result{RequeueAfter: 30 * time.Second}, nil
		}
		logger.Error(err, "DataDescriptor Handler err")
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	// If there are unfinished tasks, check again later.
	if hasPendingSources(instance) {
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	// All sources are finalized, but check if resources still need cleanup
	// Continue requeueing until resources are cleaned up
	if areAllSourcesFinalized(instance) && r.Handler.HasResourcesToCleanup(ctx, instance) {
		logger.Info("All sources finalized but resources still exist, requeueing to ensure cleanup",
			"namespace", instance.Namespace, "name", instance.Name)
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	return ctrl.Result{}, nil
}

// removeDataDescriptorFinalizer drops the delete finalizer using a fresh Get+Update
// so concurrent annotation updates (e.g. during delete prep) cannot stale RV/UID.
func (r *DataDescriptorReconciler) removeDataDescriptorFinalizer(
	ctx context.Context,
	nn client.ObjectKey,
	logger logr.Logger,
) (ctrl.Result, error) {
	logger.Info("All resources cleaned up, removing finalizer",
		"feature", "delete_normal_dac_sync",
		"step", "remove_finalizer_begin")

	latest := &dacv1alpha1.DataDescriptor{}
	if err := r.Client.Get(ctx, nn, latest); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{RequeueAfter: 10 * time.Second}, err
	}
	if !controllerutil.ContainsFinalizer(latest, dataDescriptorFinalizer) {
		logger.Info("Finalizer already removed, deletion complete")
		return ctrl.Result{}, nil
	}

	controllerutil.RemoveFinalizer(latest, dataDescriptorFinalizer)
	if err := r.Client.Update(ctx, latest); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		if apierrors.IsConflict(err) {
			logger.Info("Conflict removing finalizer, will retry")
			return ctrl.Result{RequeueAfter: 2 * time.Second}, nil
		}
		if apierrors.IsInvalid(err) {
			// Object may already be gone (UID precondition / stale cache).
			logger.Info("Invalid error removing finalizer, treating as already deleted", "error", err)
			return ctrl.Result{}, nil
		}
		logger.Error(err, "Failed to remove finalizer")
		return ctrl.Result{RequeueAfter: 10 * time.Second}, err
	}
	logger.Info("Finalizer removed, DataDescriptor will be deleted",
		"feature", "delete_normal_dac_sync",
		"step", "remove_finalizer_done")
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

// areAllSourcesFinalized checks if all data sources have reached a final state (not PENDING).
func areAllSourcesFinalized(dd *dacv1alpha1.DataDescriptor) bool {
	if len(dd.Status.SourceStatuses) == 0 {
		return false // No sources, can't be finalized
	}

	for _, status := range dd.Status.SourceStatuses {
		// PENDING means still processing, not finalized
		if status.Phase == "PENDING" {
			return false
		}
	}

	// All sources have reached a final state (Ready, Error, FAILURE, etc.)
	return true
}

// SetupWithManager sets up the controller with the Manager.
func (r *DataDescriptorReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&dacv1alpha1.DataDescriptor{}).
		Named("datadescriptor").
		Complete(r)
}
