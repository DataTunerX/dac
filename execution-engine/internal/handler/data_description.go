package handler

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"reflect"
	"sort"
	"strings"
	"time"

	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
	apiclient "github.com/DataTunerX/dac/execution-engine/client/http"
	"github.com/DataTunerX/dac/execution-engine/client/k8s"
	"github.com/DataTunerX/dac/execution-engine/internal/generator"
	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// PreCheckLLMConfig validates that the LLM ConfigMap referenced by the DD's configuration
// exists before finalizer is added. This prevents the situation where a DD gets a finalizer
// but can never complete (and therefore can never be deleted) because the LLM ConfigMap is missing.
func (h *DataDescriptorHandler) PreCheckLLMConfig(ctx context.Context, dd *dacv1alpha1.DataDescriptor) error {
	// Read the global dd-configuration to find the LLM ConfigMap name
	configMap := &corev1.ConfigMap{}
	err := h.Kubeclient.Get(ctx, client.ObjectKey{Name: "dd-configuration", Namespace: "dac"}, configMap)
	if err != nil {
		if apierrors.IsNotFound(err) {
			h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name).
				Info("dd-configuration ConfigMap not found in dac namespace, will check later during deployment generation")
			return nil
		}
		return fmt.Errorf("failed to get dd-configuration ConfigMap: %w", err)
	}

	llmConfigName := configMap.Data["llm-config"]
	if llmConfigName == "" {
		h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name).
			Info("llm-config not configured in dd-configuration, will use default during deployment generation")
		return nil
	}

	// Validate that the referenced LLM ConfigMap exists in the DD's namespace
	llmConfigMap := &corev1.ConfigMap{}
	err = h.Kubeclient.Get(ctx, client.ObjectKey{Name: llmConfigName, Namespace: dd.Namespace}, llmConfigMap)
	if err != nil {
		if apierrors.IsNotFound(err) {
			return fmt.Errorf("LLM ConfigMap %q not found in namespace %q: the referenced LLM configuration does not exist. "+
				"Please create the ConfigMap first, then retry", llmConfigName, dd.Namespace)
		}
		return fmt.Errorf("failed to check LLM ConfigMap %q in namespace %q: %w", llmConfigName, dd.Namespace, err)
	}

	h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name).
		Info("LLM ConfigMap pre-check passed", "configMapName", llmConfigName)
	return nil
}

// clearSyncRequestedAtAnnotation removes dac.dac.io/sync-requested-at using a fresh GET + merge patch.
func (h *DataDescriptorHandler) clearSyncRequestedAtAnnotation(ctx context.Context, namespace, name string, logger logr.Logger) error {
	fresh := &dacv1alpha1.DataDescriptor{}
	key := types.NamespacedName{Namespace: namespace, Name: name}
	if err := h.Kubeclient.Get(ctx, key, fresh); err != nil {
		return fmt.Errorf("get DataDescriptor before clearing sync-requested-at: %w", err)
	}
	if fresh.Annotations == nil || fresh.Annotations[annotationSyncRequestedAt] == "" {
		return nil
	}
	modified := fresh.DeepCopy()
	delete(modified.Annotations, annotationSyncRequestedAt)
	if err := h.Kubeclient.Patch(ctx, modified, client.MergeFrom(fresh)); err != nil {
		return fmt.Errorf("clear sync-requested-at annotation: %w", err)
	}
	logger.Info(
		"resync path: cleared sync-requested-at after data-sinker deployment was ensured",
		"feature", "sync_requested_at_resync",
		"step", "annotation_clear_after_deployment_ensured",
	)
	return nil
}

// resetStatusForObserverResync transitions the DD out of Ready so handleDDStatus does not treat
// stale SourceStatuses as complete (which would skip the status API and trigger immediate cleanup).
// Semantic domain and other sinker work re-run via the new job; data-sinkers uses update-if-exists for SD.
func (h *DataDescriptorHandler) resetStatusForObserverResync(ctx context.Context, dd *dacv1alpha1.DataDescriptor) error {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	key := types.NamespacedName{Namespace: dd.Namespace, Name: dd.Name}
	fresh := &dacv1alpha1.DataDescriptor{}
	if err := h.Kubeclient.Get(ctx, key, fresh); err != nil {
		return fmt.Errorf("get DataDescriptor before observer resync status reset: %w", err)
	}

	newStatus := fresh.Status.DeepCopy()
	newStatus.OverallPhase = "NotReady"

	sourceStatuses := make([]dacv1alpha1.SourceStatus, 0, len(fresh.Spec.Sources))
	for _, src := range fresh.Spec.Sources {
		sourceStatuses = append(sourceStatuses, dacv1alpha1.SourceStatus{
			Name:   src.Name,
			Phase:  "PENDING",
			TaskID: "",
		})
	}
	newStatus.SourceStatuses = sourceStatuses

	if newStatus.Conditions == nil {
		newStatus.Conditions = []dacv1alpha1.Condition{}
	}
	msg := "Re-sync requested (dac.dac.io/sync-requested-at); running data-sinker job from scratch."
	newStatus.SetDataDescriptorCondition(*dacv1alpha1.NewCondition(dacv1alpha1.ConditionUpdating, corev1.ConditionTrue, "ObserverResync", msg))
	newStatus.SetDataDescriptorCondition(*dacv1alpha1.NewCondition(dacv1alpha1.ConditionNotReady, corev1.ConditionTrue, "NotReady", "Re-sync in progress: waiting for data-sinker job."))
	newStatus.SetDataDescriptorCondition(*dacv1alpha1.NewCondition(dacv1alpha1.ConditionAvailable, corev1.ConditionFalse, "ResyncPending", msg))

	if h.isStatusEqualIgnoringTime(fresh.Status, *newStatus) {
		dd.Status = fresh.Status
		return nil
	}

	fresh.Status = *newStatus
	if err := h.Kubeclient.Status().Update(ctx, fresh); err != nil {
		return fmt.Errorf("reset DataDescriptor status for observer resync: %w", err)
	}
	dd.Status = fresh.Status
	logger.Info(
		"resync path: DD status reset to NotReady + PENDING sources for full data-sinker re-run",
		"feature", "sync_requested_at_resync",
		"step", "status_reset_observer_resync",
	)
	return nil
}

type DataDescriptorHandler struct {
	K8sServices k8s.Services
	EventsCli   k8s.Event
	Kubeclient  client.Client
	Logger      logr.Logger
	HTTPClient  *apiclient.APIClient
}

// SourceStatusResult contains the result of checking a data source status
type SourceStatusResult struct {
	Name         string
	Phase        string
	LastSyncTime metav1.Time
	Records      int64
	TaskID       string
	Error        error
}

// StatusAPIResponse represents the response from data-sinker-status service
type StatusAPIResponse struct {
	Status    string `json:"status"`
	TaskID    string `json:"task_id"`
	Timestamp string `json:"timestamp"`
	Error     string `json:"error"`
}

// errDataDescriptorGone is returned when the DD was deleted or is being deleted while waiting for deployment.
var errDataDescriptorGone = fmt.Errorf("data descriptor deleted or being deleted")

// logResyncDSDACContext records ds-type DataAgentContainers that reference this DD.
// They are separate resources from the DD-scoped data-sinker Deployment
// (generator.DataDescriptorResourceName); ds DAC existence does not bypass observer resync logic.
func (h *DataDescriptorHandler) logResyncDSDACContext(ctx context.Context, logger logr.Logger, dd *dacv1alpha1.DataDescriptor) {
	allDACs := &dacv1alpha1.DataAgentContainerList{}
	if err := h.Kubeclient.List(ctx, allDACs, client.InNamespace(dd.Namespace)); err != nil {
		logger.Info(
			"resync path: could not list DataAgentContainers for ds DAC context",
			"feature", "sync_requested_at_resync",
			"step", "ds_dac_context_list_error",
			"error", err.Error(),
		)
		return
	}
	var dsDACNames []string
	for i := range allDACs.Items {
		dac := &allDACs.Items[i]
		if dac.Spec.DACType != "ds" {
			continue
		}
		for _, sel := range dac.Spec.DataPolicy.SourceNameSelector {
			if strings.TrimSpace(sel) == dd.Name {
				dsDACNames = append(dsDACNames, dac.Name)
				break
			}
		}
	}
	logger.Info(
		"resync path: ds DataAgentContainers referencing this DD (do not replace DD data-sinker Deployment)",
		"feature", "sync_requested_at_resync",
		"step", "ds_dac_context",
		"dsDacNames", dsDACNames,
		"note", "ensureAutoDAC is not called on this path; if job does not re-run, see deployment_probe and skip_create_existing_deployment.",
	)
}

// isTemporaryNetworkError checks if the error is a temporary network error (e.g., connection refused, timeout)
// that typically occurs when a service is starting up. These should be treated as PENDING, not ERROR.
func isTemporaryNetworkError(err error) bool {
	if err == nil {
		return false
	}
	errStr := err.Error()
	// Check for common temporary network errors
	if strings.Contains(errStr, "connection refused") ||
		strings.Contains(errStr, "dial tcp") ||
		strings.Contains(errStr, "timeout") ||
		strings.Contains(errStr, "no such host") ||
		strings.Contains(errStr, "connection reset") {
		return true
	}
	// Check for net.OpError (connection refused, timeout, etc.)
	var opErr *net.OpError
	if errors.As(err, &opErr) {
		return true
	}
	// Check for net.DNSError (DNS lookup failures)
	var dnsErr *net.DNSError
	if errors.As(err, &dnsErr) {
		return true
	}
	return false
}

// isDataDescriptorGone returns true if the DataDescriptor no longer exists or has DeletionTimestamp set.
func (h *DataDescriptorHandler) isDataDescriptorGone(ctx context.Context, namespace, name string) bool {
	dd := &dacv1alpha1.DataDescriptor{}
	err := h.Kubeclient.Get(ctx, types.NamespacedName{Namespace: namespace, Name: name}, dd)
	if err != nil {
		return apierrors.IsNotFound(err)
	}
	return dd.DeletionTimestamp != nil
}

// waitForDeploymentReady waits for deployment to be ready (all replicas available).
// If the DataDescriptor is deleted or being deleted and the deployment is gone, it returns errDataDescriptorGone.
func (h *DataDescriptorHandler) waitForDeploymentReady(ctx context.Context, namespace, deploymentName, ddName string) error {
	logger := h.Logger.WithValues("namespace", namespace, "deployment", deploymentName)

	checkInterval := 5 * time.Second
	ticker := time.NewTicker(checkInterval)
	defer ticker.Stop()

	// First check immediately
	if ready, err := h.checkDeploymentReady(namespace, deploymentName, logger); err == nil && ready {
		return nil
	}
	if _, err := h.checkDeploymentReady(namespace, deploymentName, logger); err != nil && h.isDataDescriptorGone(ctx, namespace, ddName) {
		return errDataDescriptorGone
	}

	for {
		// Check if context is cancelled
		select {
		case <-ctx.Done():
			return fmt.Errorf("context cancelled while waiting for deployment: %w", ctx.Err())
		case <-ticker.C:
			// Continue to check deployment status
		}

		ready, err := h.checkDeploymentReady(namespace, deploymentName, logger)
		if err == nil && ready {
			return nil
		}
		// Deployment not found and DD deleted or being deleted -> stop waiting
		if err != nil && h.isDataDescriptorGone(ctx, namespace, ddName) {
			return errDataDescriptorGone
		}
	}
}

// checkDeploymentReady checks if deployment is ready and returns (ready, error)
func (h *DataDescriptorHandler) checkDeploymentReady(namespace, deploymentName string, logger logr.Logger) (bool, error) {
	deployment, err := h.K8sServices.GetDeployment(namespace, deploymentName)
	if err != nil {
		logger.Info("Deployment not found yet, waiting...", "error", err)
		return false, err
	}

	// Check if deployment is ready
	if deployment.Status.ReadyReplicas == *deployment.Spec.Replicas &&
		deployment.Status.ReadyReplicas > 0 &&
		deployment.Status.Replicas == *deployment.Spec.Replicas {
		logger.Info("Deployment is ready",
			"readyReplicas", deployment.Status.ReadyReplicas,
			"desiredReplicas", *deployment.Spec.Replicas)
		return true, nil
	}

	logger.Info("Deployment not ready yet",
		"readyReplicas", deployment.Status.ReadyReplicas,
		"desiredReplicas", *deployment.Spec.Replicas,
		"replicas", deployment.Status.Replicas)
	return false, nil
}

// DoAddOrUpdate 仅在「该 DD 还没有 deployment」时创建 ConfigMap 和 deployment（真正收到/创建 DD 时）。
// Manager 重启后 controller 会 List 所有 DD 并逐个 Reconcile；若 deployment 已存在则只做状态同步，不重写 ConfigMap、不创建 deployment。
// 之前「过一会就被删」是错误逻辑：Add/Update 在「所有 source 就绪」后误调用了 cleanup，已修复为 Add/Update 从不清理。
func (h *DataDescriptorHandler) DoAddOrUpdate(ctx context.Context, dd *dacv1alpha1.DataDescriptor) error {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("DoAddOrUpdate Processing DataDescriptor")

	// Tracks dd-sync-observer resync path (reset DD status only when entering from Ready+annotation).
	// hadSyncRequestedAt: if true, clear dac.dac.io/sync-requested-at after Deployment is ensured.
	// That must not be gated on resyncFromObserver alone: if observer PATCHes again while DD is already
	// NotReady (mid job), resyncFromObserver is false and leaving the annotation stranded causes
	// Ready+annotation on the next reconcile → endless data-sinker job loops.
	resyncFromObserver := false
	hadSyncRequestedAt := dd.Annotations != nil && strings.TrimSpace(dd.Annotations[annotationSyncRequestedAt]) != ""

	// Skip create/update when DD is being deleted (controller handles deletion separately)
	if dd.DeletionTimestamp != nil {
		logger.Info("DataDescriptor is being deleted, skipping DoAddOrUpdate")
		return nil
	}

	// DD 已完成（OverallPhase Ready）时，deployment 已被 cleanupCompletedDeployment 清理；
	// 重启时不应再创建 deployment，否则会重复跑 data-sinker job。
	// 但当 observer 设置了 sync-requested-at 时，需清除该 annotation 并重新创建 deployment 触发 re-sync。
	if dd.Status.OverallPhase == "Ready" {
		if hadSyncRequestedAt {
			resyncFromObserver = true
			logger.Info(
				"dd-sync observer: sync-requested-at present; will ensure data-sinker deployment then clear annotation",
				"feature", "sync_requested_at_resync",
				"annotation", annotationSyncRequestedAt,
				"annotationValue", dd.Annotations[annotationSyncRequestedAt],
				"dataSinkerDeploymentName", generator.DataDescriptorResourceName(dd),
				"note", "Deployment name is dd-<DataDescriptor.metadata.name> (dd- prefix), not the bare DD name.",
			)
			// Do not clear annotation yet — if ConfigMap/Deployment create fails, keep annotation for retry.
		} else {
			// Ready but observer did not request resync: we do not create/manage DD job Deployment here.
			// If Deployment is missing, that is usually normal (post-success cleanup); if unexpected, prior
			// reconcile errors or stuck annotation logic are the place to look.
			idleDeployName := generator.DataDescriptorResourceName(dd)
			_, idleDepErr := h.K8sServices.GetDeployment(dd.Namespace, idleDeployName)
			idleDepExists := idleDepErr == nil
			logger.Info(
				"Ready DD without sync-requested-at: early-return path (ensureAutoDAC only, no DD data-sinker Deployment create)",
				"feature", "dd_ready_idle_path",
				"step", "early_return_ensure_auto_dac_only",
				"deploymentName", idleDeployName,
				"dataSinkerDeploymentExists", idleDepExists,
				"getDeploymentErr", fmt.Sprintf("%v", idleDepErr),
				"explain", "New job stack only runs when dac.dac.io/sync-requested-at is set or DD is non-Ready. Missing Deployment after cleanup is expected.",
			)
			if !idleDepExists && idleDepErr != nil && apierrors.IsNotFound(idleDepErr) {
				logger.Info(
					"Ready + no resync annotation + no dd-* Deployment: idle cluster state (typical after handleDDStatus cleanup). To run data-sinker again, rely on dd-sync-observer or set sync-requested-at.",
					"feature", "dd_ready_idle_path",
					"step", "no_deployment_expected_idle",
					"deploymentName", idleDeployName,
				)
			}
			logger.Info("DataDescriptor already completed (OverallPhase Ready), skipping deployment create")
			// Ensure auto-created DACs exist (idempotent — skips if already present)
			if err := h.ensureAutoDAC(ctx, dd); err != nil {
				logger.Error(err, "Failed to ensure ds DAC for already-Ready DD")
			}
			requeue, err := h.ensureAutoNormalDAC(ctx, dd)
			if err != nil {
				logger.Error(err, "Failed to ensure normal DAC for already-Ready DD")
			}
			if requeue {
				return ErrRequeueNeeded
			}
			return nil
		}
	}

	if resyncFromObserver {
		if err := h.resetStatusForObserverResync(ctx, dd); err != nil {
			return fmt.Errorf("observer resync: reset status for re-run: %w", err)
		}
	}

	deploymentName := generator.DataDescriptorResourceName(dd)
	_, err := h.K8sServices.GetDeployment(dd.Namespace, deploymentName)
	deploymentExists := err == nil
	if hadSyncRequestedAt {
		logger.Info(
			"resync path: probed data-sinker deployment",
			"feature", "sync_requested_at_resync",
			"step", "deployment_probe",
			"deploymentName", deploymentName,
			"deploymentExists", deploymentExists,
			"getDeploymentErr", fmt.Sprintf("%v", err),
		)
		h.logResyncDSDACContext(ctx, logger, dd)
	}

	if !deploymentExists {
		// 仅当 deployment 不存在时创建 ConfigMap 和 deployment（真正创建 DD 或首次 Reconcile）
		// 1. 为 data-sinker-job 生成 ConfigMap（operation: AddOrUpdate）
		if hadSyncRequestedAt {
			logger.Info(
				"resync path: deployment missing — creating ConfigMap then Deployment",
				"feature", "sync_requested_at_resync",
				"step", "create_configmap_and_deployment",
				"deploymentName", deploymentName,
			)
		}
		if err := h.createOrUpdateDataSinkerJobConfigMap(ctx, dd); err != nil {
			if hadSyncRequestedAt {
				logger.Error(err,
					"resync path: createOrUpdateDataSinkerJobConfigMap failed; sync-requested-at was NOT cleared — will retry on next reconcile",
					"feature", "sync_requested_at_resync",
					"step", "create_configmap_failed_keeps_annotation",
					"deploymentName", deploymentName,
				)
			}
			return fmt.Errorf("failed to create/update data-sinker job configmap: %w", err)
		}
		// 2. 创建 deployment（包含 data-sinker-job / data-sinker-status / dac-data-services）
		ddGenerator := &generator.DataDescriptorGenerator{
			K8sServices: h.K8sServices,
			Kubeclient:  h.Kubeclient,
			Logger:      h.Logger.WithName("DataDescriptorGenerator"),
		}
		logger.Info("Creating deployment for DataDescriptor")
		if err := ddGenerator.Do(ctx, dd); err != nil {
			if hadSyncRequestedAt {
				logger.Error(err,
					"resync path: DataDescriptorGenerator.Do failed; sync-requested-at was NOT cleared — will retry on next reconcile",
					"feature", "sync_requested_at_resync",
					"step", "deployment_do_failed_keeps_annotation",
					"deploymentName", deploymentName,
				)
			}
			return fmt.Errorf("failed to create deployment for data descriptor: %w", err)
		}
		if hadSyncRequestedAt {
			logger.Info(
				"resync path: DataDescriptorGenerator.Do completed (deployment create submitted)",
				"feature", "sync_requested_at_resync",
				"step", "deployment_create_done",
				"deploymentName", deploymentName,
			)
		}
	} else {
		logger.Info("Deployment already exists, skipping ConfigMap/deployment create (status sync only)")
		if hadSyncRequestedAt {
			logger.Info(
				"resync path: deployment already exists — no new Deployment/ConfigMap; only wait + status sync. "+
					"If full re-sync was expected, cleanup may not have removed this Deployment or a race kept it alive.",
				"feature", "sync_requested_at_resync",
				"step", "skip_create_existing_deployment",
				"deploymentName", deploymentName,
			)
		}
	}

	if hadSyncRequestedAt {
		if err := h.clearSyncRequestedAtAnnotation(ctx, dd.Namespace, dd.Name, logger); err != nil {
			logger.Error(err, "resync path: failed to clear sync-requested-at after ensuring deployment",
				"feature", "sync_requested_at_resync",
				"step", "annotation_clear_failed",
				"deploymentName", deploymentName,
			)
			return err
		}
		if dd.Annotations != nil {
			delete(dd.Annotations, annotationSyncRequestedAt)
		}
	}

	logger.Info("Waiting for deployment to be ready", "deployment", deploymentName)
	if hadSyncRequestedAt {
		logger.Info(
			"resync path: waiting for deployment ready (up to 5m)",
			"feature", "sync_requested_at_resync",
			"step", "wait_deployment_ready_begin",
			"deploymentName", deploymentName,
		)
	}
	waitCtx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()

	if err := h.waitForDeploymentReady(waitCtx, dd.Namespace, deploymentName, dd.Name); err != nil {
		if hadSyncRequestedAt {
			logger.Error(err, "resync path: wait for deployment ready failed or timed out",
				"feature", "sync_requested_at_resync",
				"step", "wait_deployment_ready_error",
				"deploymentName", deploymentName,
			)
		}
		if err == errDataDescriptorGone {
			return nil // DD deleted, no need to requeue with error
		}
		return fmt.Errorf("deployment not ready: %w", err)
	}
	logger.Info("Deployment is ready, start checking data-sinker job status via status service")
	if hadSyncRequestedAt {
		logger.Info(
			"resync path: deployment ready — calling handleDDStatus",
			"feature", "sync_requested_at_resync",
			"step", "handle_dd_status_begin",
			"deploymentName", deploymentName,
		)
	}

	// 3. 通过 data-sinker-status 判断 job 状态并更新 dd.Status
	taskIDs := make(map[string]string) // 保持签名一致，目前不再使用 taskID
	if err := h.handleDDStatus(ctx, dd, taskIDs); err != nil {
		if hadSyncRequestedAt {
			logger.Error(err, "resync path: handleDDStatus failed",
				"feature", "sync_requested_at_resync",
				"step", "handle_dd_status_error",
			)
		}
		return fmt.Errorf("failed to update status: %w", err)
	}
	if hadSyncRequestedAt {
		logger.Info(
			"resync path: DoAddOrUpdate finished after observer resync (handleDDStatus ok)",
			"feature", "sync_requested_at_resync",
			"step", "handle_dd_status_ok",
			"deploymentName", deploymentName,
		)
	}

	return nil
}

func (h *DataDescriptorHandler) DoDelete(ctx context.Context, namespace string, name string) (string, error) {
	logger := h.Logger.WithValues("namespace", namespace, "name", name)
	logger.Info("DoDelete Processing DataDescriptor")

	taskID, err := h.handleDDDelete(ctx, namespace, name)
	if err != nil {
		return "", fmt.Errorf("failed to delete data descriptor: %w", err)
	}
	logger.Info("Delete task ID", "taskID", taskID)
	return taskID, nil
}

func (h *DataDescriptorHandler) handleDD(ctx context.Context, dd *dacv1alpha1.DataDescriptor) (map[string]string, error) {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("handleDD Processing DataDescriptor sources")

	taskIDs := make(map[string]string)

	for _, source := range dd.Spec.Sources {
		promptConfigmapName := ""

		if source.Prompts != nil {
			promptConfigmapName = source.Prompts.Prompts.Name
		}

		fewshotsAndBackgroudKnowledge, err := h.getFewshotsAndBackgroudKnowledgeFromConfigmap(ctx, dd, promptConfigmapName)
		if err != nil {
			logger.Error(err, "Failed to get fewshots and backgroudKnowledge from Configmap for dd", "promptConfigmapName", promptConfigmapName, "dd", dd.Name, "namespace", dd.Namespace)
		}

		logger.Info("process prompt", "prompt", fewshotsAndBackgroudKnowledge)

		// Check if there are any valid existing tasks.
		if existingStatus := h.getExistingSourceStatus(dd, source.Name); existingStatus != nil {
			if existingStatus.TaskID != "" {
				logger.Info("Skipping source with existing task",
					"source", source.Name,
					"taskID", existingStatus.TaskID)
				taskIDs[source.Name] = existingStatus.TaskID
				continue
			}
		}

		// Construct a request data structure that complies with API requirements.
		requestData := map[string]interface{}{
			"data": map[string]interface{}{
				"operation": "AddOrUpdate",
				"source": map[string]interface{}{
					"type":     source.Type,
					"name":     source.Name,
					"metadata": source.Metadata,
				},
				"descriptor": map[string]interface{}{
					"name":      dd.Name,
					"namespace": dd.Namespace,
				},
				"extract":        source.Extract,
				"prompts":        fewshotsAndBackgroudKnowledge,
				"codeRepo":       source.CodeRepo,
				"processing":     source.Processing,
				"classification": source.Classification,
			},
		}

		// 旧逻辑：通过 Celery 触发任务，已废弃
		_ = requestData
	}

	return taskIDs, nil
}

// createDeleteDataSinkerJobConfigMap 为删除操作创建 ConfigMap
// ConfigMap 内容为 operation: "Delete" 的简化结构
func (h *DataDescriptorHandler) createDeleteDataSinkerJobConfigMap(ctx context.Context, dd *dacv1alpha1.DataDescriptor) error {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("Creating delete job ConfigMap for DataDescriptor")

	// 构造删除操作所需的 data 结构
	data := map[string]interface{}{
		"operation": "Delete",
		"descriptor": map[string]interface{}{
			"name":      dd.Name,
			"namespace": dd.Namespace,
		},
	}

	jsonBytes, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal delete job config data to JSON: %w", err)
	}

	configMapName := generator.DataDescriptorResourceName(dd)

	// 如果 DD 对象存在且有 UID，设置 OwnerReference；否则不设置（对象已删除）
	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      configMapName,
			Namespace: dd.Namespace,
		},
		Data: map[string]string{
			"data.json": string(jsonBytes),
		},
	}

	// 只有当 DD 对象存在且有 UID 时才设置 OwnerReference
	if dd.UID != "" {
		isController := true
		cm.OwnerReferences = []metav1.OwnerReference{
			{
				APIVersion: dd.APIVersion,
				Kind:       dd.Kind,
				Name:       dd.Name,
				UID:        dd.UID,
				Controller: &isController,
			},
		}
	}

	if err := h.K8sServices.CreateOrUpdateConfigMap(dd.Namespace, cm); err != nil {
		return fmt.Errorf("failed to create or update ConfigMap %s/%s: %w", dd.Namespace, configMapName, err)
	}

	logger.Info("Delete job ConfigMap created/updated successfully",
		"configMap", configMapName,
		"data", string(jsonBytes))
	return nil
}

// createOrUpdateDataSinkerJobConfigMap 为 data-sinker-job 生成 /app/data.json 对应的 ConfigMap
// ConfigMap 名称约定为：dd-<dd.Name>，key 为 "data.json"
// 内容为原来发给 Celery 的 data 字段（即 job-testdata.json 的结构）
func (h *DataDescriptorHandler) createOrUpdateDataSinkerJobConfigMap(ctx context.Context, dd *dacv1alpha1.DataDescriptor) error {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("Creating/Updating data-sinker job ConfigMap for DataDescriptor")

	if len(dd.Spec.Sources) == 0 {
		return fmt.Errorf("no sources defined in DataDescriptor %s/%s", dd.Namespace, dd.Name)
	}

	// 当前实现：仅使用第一个 source 生成 job 配置（与 job-testdata.json 一致）
	source := dd.Spec.Sources[0]

	// 获取 prompts（fewshots + background_knowledge）
	promptConfigmapName := ""
	if source.Prompts != nil {
		promptConfigmapName = source.Prompts.Prompts.Name
	}
	fewshotsAndBackgroudKnowledge, err := h.getFewshotsAndBackgroudKnowledgeFromConfigmap(ctx, dd, promptConfigmapName)
	if err != nil {
		logger.Error(err, "Failed to get fewshots and backgroudKnowledge from Configmap for dd",
			"promptConfigmapName", promptConfigmapName, "dd", dd.Name, "namespace", dd.Namespace)
	}

	// 构造 data-sinker-job 所需的 data 结构（等同于 job-testdata.json）
	data := map[string]interface{}{
		"operation": "AddOrUpdate",
		"source": map[string]interface{}{
			"type":     source.Type,
			"name":     source.Name,
			"metadata": source.Metadata,
		},
		"descriptor": map[string]interface{}{
			"name":      dd.Name,
			"namespace": dd.Namespace,
		},
		"extract":        source.Extract,
		"prompts":        fewshotsAndBackgroudKnowledge,
		"codeRepo":       source.CodeRepo,
		"processing":     source.Processing,
		"classification": source.Classification,
	}

	jsonBytes, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal job config data to JSON: %w", err)
	}

	configMapName := generator.DataDescriptorResourceName(dd)

	isController := true
	ownerRefs := []metav1.OwnerReference{
		{
			APIVersion: dd.APIVersion,
			Kind:       dd.Kind,
			Name:       dd.Name,
			UID:        dd.UID,
			Controller: &isController,
		},
	}

	cm := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:            configMapName,
			Namespace:       dd.Namespace,
			Labels:          map[string]string{"data": dd.Name},
			OwnerReferences: ownerRefs,
		},
		Data: map[string]string{
			"data.json": string(jsonBytes),
		},
	}

	if err := h.K8sServices.CreateOrUpdateConfigMap(dd.Namespace, cm); err != nil {
		return fmt.Errorf("failed to create or update ConfigMap %s/%s: %w", dd.Namespace, configMapName, err)
	}

	logger.Info("Data-sinker job ConfigMap created/updated successfully",
		"configMap", configMapName, "data", string(jsonBytes))
	return nil
}

// handleDDDelete handles the deletion of DataDescriptor using the same logic as Add/Update
// It creates a ConfigMap with operation: "Delete" and a Deployment to execute the deletion
func (h *DataDescriptorHandler) handleDDDelete(ctx context.Context, namespace string, name string) (string, error) {
	logger := h.Logger.WithValues("namespace", namespace, "name", name)
	logger.Info("Delete DataDescriptor - using same logic as Add/Update")

	// 尝试获取 DD 对象，如果不存在则创建最小化对象用于删除任务
	dd := &dacv1alpha1.DataDescriptor{}
	if err := h.Kubeclient.Get(ctx, types.NamespacedName{Namespace: namespace, Name: name}, dd); err != nil {
		if apierrors.IsNotFound(err) {
			logger.Info("DataDescriptor not found, creating minimal instance for deletion task", "namespace", namespace, "name", name)
			// DD 对象不存在，创建最小化对象用于删除任务
			// 删除操作只需要 name 和 namespace，不需要完整的 spec
			// 但需要设置 APIVersion 和 Kind 以便 generator 正常工作
			dd = &dacv1alpha1.DataDescriptor{
				TypeMeta: metav1.TypeMeta{
					APIVersion: "dac.dac.io/v1alpha1",
					Kind:       "DataDescriptor",
				},
				ObjectMeta: metav1.ObjectMeta{
					Name:      name,
					Namespace: namespace,
					// UID 为空，不会设置 OwnerReference，资源独立存在直到删除任务完成
				},
				// 删除操作不需要 spec，只需要 name 和 namespace
			}
		} else {
			return "", fmt.Errorf("failed to get DataDescriptor: %w", err)
		}
	}

	// 0. 检查是否已有 deployment 存在（可能是创建流程创建的）
	// 如果存在且是 Add/Update 任务，需要先等add的deployment任务完成，避免冲突
	deploymentName := generator.DataDescriptorResourceName(dd)
	configMapName := generator.DataDescriptorResourceName(dd)

	// 提前声明 ddGenerator，避免 goto 跳过变量声明
	ddGenerator := &generator.DataDescriptorGenerator{
		K8sServices: h.K8sServices,
		Kubeclient:  h.Kubeclient,
		Logger:      h.Logger.WithName("DataDescriptorGenerator"),
	}

	existingDeployment, err := h.K8sServices.GetDeployment(dd.Namespace, deploymentName)
	if err == nil && existingDeployment != nil {
		logger.Info("Deployment already exists, checking if it's from Add/Update operation", "deployment", deploymentName)
		// 检查 ConfigMap 的 operation 字段，判断是 Add/Update 还是 Delete
		existingConfigMap, err := h.K8sServices.GetConfigMap(dd.Namespace, configMapName)
		if err == nil && existingConfigMap != nil {
			if dataJSON, exists := existingConfigMap.Data["data.json"]; exists {
				var configData map[string]interface{}
				if err := json.Unmarshal([]byte(dataJSON), &configData); err == nil {
					if operation, ok := configData["operation"].(string); ok {
						if operation == "AddOrUpdate" {
							logger.Info("Existing deployment is from Add/Update operation, cleaning up immediately",
								"deployment", deploymentName, "operation", operation)
							// handleDDDelete 只在删除流程中被调用，说明用户已经决定删除 DD
							// 此时 AddOrUpdate 任务的结果不再重要，应该直接清理并创建删除任务
							// 不需要等待 AddOrUpdate 任务完成，因为数据最终会被删除
							h.cleanupCompletedDeployment(ctx, dd)
							// 等待并验证资源确实被删除，避免竞态条件
							// 由于 DoAddOrUpdate 已经检查了 DeletionTimestamp，理论上不会重新创建 deployment
							// 但为了更安全，我们等待并验证 deployment 确实被删除
							maxWaitVerify := 10 * time.Second
							waitInterval := 1 * time.Second
							waitStart := time.Now()
							for time.Since(waitStart) < maxWaitVerify {
								_, err := h.K8sServices.GetDeployment(dd.Namespace, deploymentName)
								if apierrors.IsNotFound(err) {
									logger.Info("Deployment confirmed deleted", "elapsed", time.Since(waitStart))
									break
								}
								time.Sleep(waitInterval)
							}
						} else if operation == "Delete" {
							logger.Info("Existing deployment is already for Delete operation, will reuse it",
								"deployment", deploymentName, "operation", operation)
							// 已经是删除任务，不需要重新创建，直接跳到等待 ready 和检查状态
							// 但需要确保 ConfigMap 是最新的（可能 DD 信息有变化）
							// 先更新 ConfigMap 确保是最新的，然后跳过创建 deployment
							if err := h.createDeleteDataSinkerJobConfigMap(ctx, dd); err != nil {
								return "", fmt.Errorf("failed to update delete job configmap: %w", err)
							}
							// 跳过创建 deployment 和重复创建 ConfigMap，直接等待 ready
							goto waitForDeployment
						}
					}
				}
			}
		}
		// 如果无法判断 operation 或 ConfigMap 不存在，直接清理
		// 因为 handleDDDelete 只在删除流程中被调用，说明用户已经决定删除 DD
		// 无论 deployment 是什么操作，都应该清理并创建删除任务
		if err != nil || existingConfigMap == nil {
			logger.Info("Cannot determine operation from ConfigMap, cleaning up existing resources immediately")
			h.cleanupCompletedDeployment(ctx, dd)
			time.Sleep(2 * time.Second)
		}
	}

	// 1. 为 data-sinker-job 创建 Delete 操作的 ConfigMap
	// 注意：如果之前已经创建（Delete 操作已存在的情况），这里会更新，是幂等的
	if err := h.createDeleteDataSinkerJobConfigMap(ctx, dd); err != nil {
		return "", fmt.Errorf("failed to create delete job configmap: %w", err)
	}

	// 2. 创建 deployment（和 Add/Update 一样的逻辑）
	// 注意：如果 deployment 是 Delete 操作已存在，前面的代码会通过 goto 跳过这里
	logger.Info("Creating deployment for DataDescriptor deletion")
	if err := ddGenerator.Do(ctx, dd); err != nil {
		return "", fmt.Errorf("failed to create deployment for data descriptor deletion: %w", err)
	}

waitForDeployment:
	logger.Info("Waiting for deployment to be ready", "deployment", deploymentName)

	// Create a context with timeout for waiting deployment
	waitCtx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()

	if err := h.waitForDeploymentReady(waitCtx, dd.Namespace, deploymentName, dd.Name); err != nil {
		if err == errDataDescriptorGone {
			return "", nil // DD deleted, no need to requeue with error
		}
		return "", fmt.Errorf("deployment not ready: %w", err)
	}
	logger.Info("Deployment is ready, start checking delete job status via status service")

	// 3. 检查删除任务状态并清理资源（与 Add/Update 相同的逻辑）
	// 删除操作也会通过 status API 检查完成状态
	taskIDs := make(map[string]string) // 保持签名一致
	if err := h.handleDDStatus(ctx, dd, taskIDs); err != nil {
		if errors.Is(err, ErrRequeueNeeded) {
			return "delete-task", ErrRequeueNeeded
		}
		return "", fmt.Errorf("failed to check delete job status: %w", err)
	}

	return "delete-task", nil
}

// areAllSourcesFinalized checks if all data sources have reached a final state (not PENDING).
// Final states include: Ready, Error, FAILURE, Invalid, etc.
// Returns true if all sources are finalized, false if any source is still PENDING.
func (h *DataDescriptorHandler) areAllSourcesFinalized(sourceStatuses []dacv1alpha1.SourceStatus) bool {
	if len(sourceStatuses) == 0 {
		return false // No sources, can't be finalized
	}

	for _, status := range sourceStatuses {
		// PENDING means still processing, not finalized
		if strings.ToUpper(status.Phase) == "PENDING" {
			return false
		}
	}

	// All sources have reached a final state (Ready, Error, FAILURE, etc.)
	return true
}

// HasResourcesToCleanup checks if Deployment, Service, or ConfigMap still exist and need to be cleaned up.
func (h *DataDescriptorHandler) HasResourcesToCleanup(ctx context.Context, dd *dacv1alpha1.DataDescriptor) bool {
	deploymentName := generator.DataDescriptorResourceName(dd)
	serviceName := generator.DataDescriptorResourceName(dd)
	configMapName := generator.DataDescriptorResourceName(dd)

	// Check if deployment exists
	_, err := h.K8sServices.GetDeployment(dd.Namespace, deploymentName)
	if err == nil {
		return true // Deployment exists
	}
	if !apierrors.IsNotFound(err) {
		// Other error, assume it exists and needs cleanup
		return true
	}

	// Check if service exists
	_, err = h.K8sServices.GetService(dd.Namespace, serviceName)
	if err == nil {
		return true // Service exists
	}
	if !apierrors.IsNotFound(err) {
		// Other error, assume it exists and needs cleanup
		return true
	}

	// Check if configmap exists
	_, err = h.K8sServices.GetConfigMap(dd.Namespace, configMapName)
	if err == nil {
		return true // ConfigMap exists
	}
	if !apierrors.IsNotFound(err) {
		// Other error, assume it exists and needs cleanup
		return true
	}

	return false // All resources don't exist
}

// CleanupResources directly cleans up resources without checking status.
// This is used when DD object is already deleted but resources still exist.
func (h *DataDescriptorHandler) CleanupResources(ctx context.Context, dd *dacv1alpha1.DataDescriptor) {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("Directly cleaning up resources for deleted DataDescriptor")
	h.cleanupCompletedDeployment(ctx, dd)
}

// GetCurrentOperationType returns the operation type of the current deployment.
// Returns "AddOrUpdate", "Delete", or "Unknown".
func (h *DataDescriptorHandler) GetCurrentOperationType(ctx context.Context, dd *dacv1alpha1.DataDescriptor) string {
	configMapName := generator.DataDescriptorResourceName(dd)

	existingConfigMap, err := h.K8sServices.GetConfigMap(dd.Namespace, configMapName)
	if err != nil {
		return "Unknown"
	}

	dataJSON, exists := existingConfigMap.Data["data.json"]
	if !exists {
		return "Unknown"
	}

	var configData map[string]interface{}
	if err := json.Unmarshal([]byte(dataJSON), &configData); err != nil {
		return "Unknown"
	}

	if operation, ok := configData["operation"].(string); ok {
		return operation
	}

	return "Unknown"
}

// CheckDeletionJobStatusAndCleanup only checks the deletion job status via status API and cleans up
// if the job has reached a final state (success/failure). It does NOT create Deployment/Service/ConfigMap.
// Use this when resources already exist to avoid recreating them after user manually deletes.
func (h *DataDescriptorHandler) CheckDeletionJobStatusAndCleanup(ctx context.Context, namespace, name string) {
	logger := h.Logger.WithValues("namespace", namespace, "name", name)
	dd := &dacv1alpha1.DataDescriptor{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: namespace},
	}
	statusResp, err := h.checkJobStatusViaStatusAPI(ctx, dd)
	if err == nil {
		statusLower := strings.ToLower(statusResp.Status)
		if statusLower == "success" || statusLower == "failure" {
			logger.Info("Delete job in final state, cleaning up resources", "status", statusResp.Status)
			if statusLower == "failure" {
				_ = h.clearSemanticGroupIDsByName(ctx, namespace, name)
			}
			h.cleanupCompletedDeployment(ctx, dd)
		} else {
			logger.Info("Delete job still in progress", "status", statusResp.Status)
		}
		return
	}
	if isTemporaryNetworkError(err) {
		logger.Info("Status API temporarily unavailable, will retry", "error", err.Error())
		return
	}
	// Other error (e.g. service gone): cleanup leftover resources only.
	logger.Info("Status API error, cleaning up resources", "error", err.Error())
	h.cleanupCompletedDeployment(ctx, dd)
}

// cleanupCompletedDeployment deletes the Deployment, Service, and ConfigMap when DataDescriptor is completed.
// This is called when DD status changes from non-Ready to Ready.
func (h *DataDescriptorHandler) cleanupCompletedDeployment(ctx context.Context, dd *dacv1alpha1.DataDescriptor) {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)

	deploymentName := generator.DataDescriptorResourceName(dd)
	serviceName := generator.DataDescriptorResourceName(dd)
	configMapName := generator.DataDescriptorResourceName(dd)

	// Delete Deployment
	if err := h.K8sServices.DeleteDeployment(dd.Namespace, deploymentName); err != nil {
		if apierrors.IsNotFound(err) {
			logger.Info("Deployment already deleted or not found", "deployment", deploymentName)
		} else {
			logger.Error(err, "Failed to delete deployment after completion", "deployment", deploymentName)
			// Don't return error, continue to delete other resources
		}
	} else {
		logger.Info("Deployment deleted after completion", "deployment", deploymentName)
	}

	// Delete Service
	if err := h.K8sServices.DeleteService(dd.Namespace, serviceName); err != nil {
		if apierrors.IsNotFound(err) {
			logger.Info("Service already deleted or not found", "service", serviceName)
		} else {
			logger.Error(err, "Failed to delete service after completion", "service", serviceName)
			// Don't return error, continue to delete configmap
		}
	} else {
		logger.Info("Service deleted after completion", "service", serviceName)
	}

	// Delete ConfigMap
	if err := h.K8sServices.DeleteConfigMap(dd.Namespace, configMapName); err != nil {
		if apierrors.IsNotFound(err) {
			logger.Info("ConfigMap already deleted or not found", "configMap", configMapName)
		} else {
			logger.Error(err, "Failed to delete configmap after completion", "configMap", configMapName)
			// Don't return error, deletion is best-effort
		}
	} else {
		logger.Info("ConfigMap deleted after completion", "configMap", configMapName)
	}
}

// Retrieve the existing SourceStatus.
func (h *DataDescriptorHandler) getExistingSourceStatus(dd *dacv1alpha1.DataDescriptor, name string) *dacv1alpha1.SourceStatus {
	for _, status := range dd.Status.SourceStatuses {
		if status.Name == name {
			return &status
		}
	}
	return nil
}

func (h *DataDescriptorHandler) handleDDStatus(ctx context.Context, dd *dacv1alpha1.DataDescriptor, taskIDs map[string]string) error {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("Processing DataDescriptor Status")

	// Save the original status for comparison later
	originalStatus := dd.Status.DeepCopy()

	// Initialize Status if needed
	newStatus := dacv1alpha1.DataDescriptorStatus{
		SourceStatuses: make([]dacv1alpha1.SourceStatus, 0),
		Conditions:     make([]dacv1alpha1.Condition, 0),
	}

	// Copy existing conditions if they exist
	if dd.Status.Conditions != nil {
		newStatus.Conditions = append(newStatus.Conditions, dd.Status.Conditions...)
	}

	// For delete operations, skip source status checks and status updates
	// Delete operations don't have sources and should only check the deletion job status
	isDeleteOperation := dd.DeletionTimestamp != nil
	var aggregatedErrors []error
	var aggregatedNotReady []string

	if !isDeleteOperation {
		// If this is a new resource, set initial condition
		if dd.Status.OverallPhase == "" {
			newStatus.SetCreateCondition("Initializing data descriptor")
		}

		// Check data source statuses (only for Add/Update operations)
		sourceStatuses := make([]dacv1alpha1.SourceStatus, len(dd.Spec.Sources))
		allHealthy := true

		for i, source := range dd.Spec.Sources {
			task := ""
			if taskID, exists := taskIDs[source.Name]; exists {
				task = taskID
			}

			status := h.checkSourceStatus(ctx, dd, source, task)

			sourceStatuses[i] = dacv1alpha1.SourceStatus{
				Name:         source.Name,
				Phase:        status.Phase,
				LastSyncTime: status.LastSyncTime,
				Records:      status.Records,
				TaskID:       status.TaskID,
			}

			if status.Error != nil || status.Phase != "Ready" {
				allHealthy = false
				if status.Error != nil {
					logger.Error(
						status.Error,
						"Data source status check failed",
						"source", source.Name,
						"phase", status.Phase,
					)
					aggregatedErrors = append(aggregatedErrors, fmt.Errorf("data source %s error: %w", source.Name, status.Error))
				} else {
					logger.Info(
						"Data source or data source task is not ready",
						"source", source.Name,
						"phase", status.Phase,
					)
					aggregatedNotReady = append(aggregatedNotReady, source.Name)
				}
			} else {
				h.EventsCli.Normal(dd, "TaskTriggered", fmt.Sprintf("Task %s Completed for data source %s", status.TaskID, source.Name))
			}
		}

		// Update the new status
		newStatus.SourceStatuses = sourceStatuses
		if allHealthy {
			newStatus.OverallPhase = "Ready"
			c := dacv1alpha1.NewCondition(dacv1alpha1.ConditionAvailable, corev1.ConditionTrue, "Available", "All data sources healthy.")
			newStatus.SetDataDescriptorCondition(*c)
			newStatus.SetDataDescriptorCondition(*dacv1alpha1.NewCondition(dacv1alpha1.ConditionUpdating, corev1.ConditionFalse, "Complete", "Data-sinker job finished successfully."))
			h.EventsCli.Normal(dd, "AllSourcesHealthy", "All data sources healthy and tasks triggered and Completed.")

			// Auto-create a "ds" type DAC for this DataDescriptor
			if err := h.ensureAutoDAC(ctx, dd); err != nil {
				logger.Error(err, "Failed to auto-create ds DAC for DataDescriptor")
				// Non-fatal: log and continue; the DAC can be created manually or on next reconcile
			}

			// Normal DAC for semantic groups is handled on the Ready early-return path
			// (ensureAutoNormalDAC) after semantic-grouper sets dac.dac.io/group-updated-at.
		} else {
			newStatus.OverallPhase = "NotReady"
			errorMsg := fmt.Sprintf("%d data sources task not completed, %d data sources have issues ", len(aggregatedNotReady), len(aggregatedErrors))
			c := dacv1alpha1.NewCondition(dacv1alpha1.ConditionNotReady, corev1.ConditionTrue, "NotReady", errorMsg)
			newStatus.SetDataDescriptorCondition(*c)
			h.EventsCli.Warning(dd, "SomeSourcesTaskErrorOrNotReady", errorMsg)
		}
	} else {
		// For delete operations, preserve existing status and don't update SourceStatuses
		// Only focus on checking deletion job status and cleanup
		logger.Info("Delete operation: skipping source status checks and status updates")
		newStatus.SourceStatuses = dd.Status.SourceStatuses // Preserve existing
		newStatus.OverallPhase = dd.Status.OverallPhase     // Preserve existing
	}

	// For delete operations, skip status updates (DD will be deleted anyway)
	// For Add/Update operations, update status if changed
	if !isDeleteOperation {
		// Compare the new status with original, ignoring time fields
		statusChanged := !h.isStatusEqualIgnoringTime(*originalStatus, newStatus)
		if statusChanged {
			// Update the status in the original object
			dd.Status = newStatus

			// Submit status update with retry for conflict errors
			maxRetries := 3
			var updateErr error
			for retry := 0; retry < maxRetries; retry++ {
				updateErr = h.Kubeclient.Status().Update(ctx, dd)
				if updateErr == nil {
					logger.Info("Status updated successfully", "retry", retry)
					break
				}
				// Check if it's a conflict error
				if apierrors.IsConflict(updateErr) {
					if retry < maxRetries-1 {
						logger.Info("Status update conflict, re-fetching object and retrying", "retry", retry+1)
						// Re-fetch the latest object
						if err := h.Kubeclient.Get(ctx, types.NamespacedName{Namespace: dd.Namespace, Name: dd.Name}, dd); err != nil {
							logger.Error(err, "Failed to re-fetch DataDescriptor after conflict")
							return fmt.Errorf("status update failed: failed to re-fetch after conflict: %w", err)
						}
						// Recalculate status based on latest object state
						// Note: We keep the newStatus we calculated, but update the dd object's resourceVersion
						dd.Status = newStatus
						time.Sleep(100 * time.Millisecond) // Brief delay before retry
						continue
					} else {
						// Max retries reached, log warning but don't fail
						logger.Info("Status update conflict after max retries, will retry in next reconcile",
							"retry", retry+1, "error", updateErr.Error())
						// Don't return error, let next reconcile handle it
						break
					}
				} else {
					// Other error, return immediately
					logger.Error(updateErr, "Failed to update status")
					return fmt.Errorf("status update failed: %w", updateErr)
				}
			}
			if updateErr != nil && !apierrors.IsConflict(updateErr) {
				return fmt.Errorf("status update failed: %w", updateErr)
			}
		} else {
			logger.Info("Status unchanged, skipping update")
		}
	} else {
		logger.Info("Delete operation: skipping status update")
	}

	// 检查是否需要清理资源
	// 对于删除操作（DeletionTimestamp 被设置），直接检查 status API，不依赖 source statuses
	// 对于 Add/Update 操作，检查所有数据源是否都是最终状态
	var shouldCleanup bool
	var deleteJobSucceeded bool
	if isDeleteOperation {
		// 删除操作：直接检查 status API 来判断任务是否完成
		logger.Info("Delete operation detected, checking status API directly")
		statusResp, err := h.checkJobStatusViaStatusAPI(ctx, dd)
		if err == nil {
			// Status API 可用，检查状态
			statusLower := strings.ToLower(statusResp.Status)
			if statusLower == "success" || statusLower == "failure" {
				shouldCleanup = true
				deleteJobSucceeded = statusLower == "success"
				logger.Info("Delete job completed (final state), cleaning up resources", "status", statusResp.Status)
			} else {
				logger.Info("Delete job still in progress", "status", statusResp.Status)
			}
		} else if isTemporaryNetworkError(err) {
			// 临时网络错误，继续等待
			logger.Info("Status API temporarily unavailable, will retry", "error", err.Error())
		} else {
			// 其他错误，可能是服务已停止或资源已清理，尝试清理资源
			logger.Info("Status API error (may be expected for delete), attempting cleanup", "error", err.Error())
			shouldCleanup = true
		}
	} else {
		// Add/Update 操作：检查所有数据源是否都是最终状态
		allSourcesFinalized := h.areAllSourcesFinalized(newStatus.SourceStatuses)
		shouldCleanup = allSourcesFinalized
		if allSourcesFinalized {
			logger.Info("All data sources reached final state (not pending)", "sourceStatuses", newStatus.SourceStatuses)
		} else {
			logger.Info("Some data sources are still pending", "sourceStatuses", newStatus.SourceStatuses)
		}
	}

	if shouldCleanup {
		logger.Info("Cleaning up deployment, service, and configmap")
		h.cleanupCompletedDeployment(ctx, dd)
		if isDeleteOperation && !deleteJobSucceeded {
			_ = h.clearSemanticGroupIDsByName(ctx, dd.Namespace, dd.Name)
		}
	} else {
		logger.Info("Keeping deployment and service, waiting for completion")
	}

	// Return aggregated errors (if any)
	if len(aggregatedErrors) > 0 {
		return fmt.Errorf("%d errors: %v", len(aggregatedErrors), aggregatedErrors)
	}
	return nil
}

// isStatusEqualIgnoringTime compares two DataDescriptorStatus objects while ignoring time fields
func (h *DataDescriptorHandler) isStatusEqualIgnoringTime(oldStatus, newStatus dacv1alpha1.DataDescriptorStatus) bool {
	// Compare OverallPhase
	if oldStatus.OverallPhase != newStatus.OverallPhase {
		return false
	}

	// Compare Conditions
	if len(oldStatus.Conditions) != len(newStatus.Conditions) {
		return false
	}
	for i := range oldStatus.Conditions {
		oldCond := oldStatus.Conditions[i]
		newCond := newStatus.Conditions[i]
		if oldCond.Type != newCond.Type ||
			oldCond.Status != newCond.Status ||
			oldCond.Reason != newCond.Reason ||
			oldCond.Message != newCond.Message {
			return false
		}
	}

	// Compare SourceStatuses (ignoring LastSyncTime)
	if len(oldStatus.SourceStatuses) != len(newStatus.SourceStatuses) {
		return false
	}
	for i := range oldStatus.SourceStatuses {
		oldSource := oldStatus.SourceStatuses[i]
		newSource := newStatus.SourceStatuses[i]
		if oldSource.Name != newSource.Name ||
			oldSource.Phase != newSource.Phase ||
			oldSource.Records != newSource.Records ||
			oldSource.TaskID != newSource.TaskID {
			return false
		}
	}

	// Compare ConsumedBy
	if !reflect.DeepEqual(oldStatus.ConsumedBy, newStatus.ConsumedBy) {
		return false
	}

	return true
}

// hasEverSucceeded checks whether the CR has ever succeeded (judged by conditions)
func (h *DataDescriptorHandler) hasEverSucceeded(dd *dacv1alpha1.DataDescriptor) bool {
	for _, condition := range dd.Status.Conditions {
		if condition.Type == dacv1alpha1.ConditionAvailable &&
			condition.Status == corev1.ConditionTrue {
			return true
		}
	}
	return false
}

// hasSourceEverSucceeded checks whether a specific data source has ever succeeded
func (h *DataDescriptorHandler) hasSourceEverSucceeded(dd *dacv1alpha1.DataDescriptor, sourceName string) bool {
	// First check if sourceStatuses has a Ready record
	if existingStatus := h.getExistingSourceStatus(dd, sourceName); existingStatus != nil {
		if existingStatus.Phase == "Ready" {
			return true
		}
	}

	// Then check if there is a global success condition
	// Because we may have cases where a single data source fails and is recreated
	return h.hasEverSucceeded(dd)
}

func (h *DataDescriptorHandler) checkSourceStatus(ctx context.Context, dd *dacv1alpha1.DataDescriptor, source dacv1alpha1.DataSource, taskID string) SourceStatusResult {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("check Source Status")

	if existingStatus := h.getExistingSourceStatus(dd, source.Name); existingStatus != nil {
		if existingStatus.Phase == "Ready" {
			logger.Info("Data source already completed", "source", source.Name)
			return SourceStatusResult{
				Name:   source.Name,
				Phase:  "Ready",
				TaskID: existingStatus.TaskID,
			}
		}
	}

	// 新逻辑：通过 data-sinker-status 服务检查 data-sinker-job 是否完成
	statusResp, err := h.checkJobStatusViaStatusAPI(ctx, dd)
	if err != nil {
		// 区分临时性网络错误（服务启动中）和真正的错误
		if isTemporaryNetworkError(err) {
			logger.Info("Status API temporarily unavailable (service may be starting), treating as pending",
				"source", source.Name,
				"error", err.Error())
			return SourceStatusResult{
				Name:  source.Name,
				Phase: "PENDING",
				Error: nil, // 临时性错误，不设置 Error
			}
		}
		// 真正的错误（如配置错误、权限问题等）
		logger.Error(err, "Failed to check job status via status API", "source", source.Name)
		return SourceStatusResult{
			Name:  source.Name,
			Phase: "Error",
			Error: fmt.Errorf("failed to check job status via status API: %w", err),
		}
	}

	logger.Info("Data-sinker job status via status API",
		"source", source.Name,
		"status", statusResp.Status,
		"taskID", statusResp.TaskID)

	switch strings.ToLower(statusResp.Status) {
	case "success":
		return SourceStatusResult{
			Name:   source.Name,
			Phase:  "Ready",
			TaskID: statusResp.TaskID,
		}
	case "failure":
		errMsg := statusResp.Error
		if errMsg == "" {
			errMsg = "data-sinker job failed (see status API for details)"
		}
		return SourceStatusResult{
			Name:  source.Name,
			Phase: "FAILURE",
			Error: fmt.Errorf("%s", errMsg),
		}
	default:
		// 其它状态（如还未写入 status.json 或处理中），视为未就绪
		return SourceStatusResult{
			Name:   source.Name,
			Phase:  "PENDING",
			TaskID: statusResp.TaskID,
		}
	}
}

// checkJobStatusViaStatusAPI 调用 data-sinker-status 容器提供的 /status 接口
// data-sinker-status 容器监听 8001，Service 暴露为 8001，避免与 dac-data-services(8000) 冲突
// 通过 Service:  http://dd-<dd-name>.<namespace>.svc.cluster.local:8001/status
func (h *DataDescriptorHandler) checkJobStatusViaStatusAPI(ctx context.Context, dd *dacv1alpha1.DataDescriptor) (*StatusAPIResponse, error) {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)

	serviceName := generator.DataDescriptorResourceName(dd)
	url := fmt.Sprintf("http://%s.%s.svc.cluster.local:8001/status", serviceName, dd.Namespace)

	logger.Info("Checking job status via status API", "url", url)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("create status API request failed: %w", err)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("status API request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("unexpected status code from status API: %d, body: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read status API response failed: %w", err)
	}

	var statusResp StatusAPIResponse
	if err := json.Unmarshal(body, &statusResp); err != nil {
		return nil, fmt.Errorf("unmarshal status API response failed: %w", err)
	}

	return &statusResp, nil
}

// checkDataSourceConnectivity checks the Connectivy of a single data source
func (h *DataDescriptorHandler) checkDataSourceConnectivity(ctx context.Context, source dacv1alpha1.DataSource) SourceStatusResult {
	// Validate data source configuration
	if source.Name == "" {
		return SourceStatusResult{
			Name:  source.Name,
			Phase: "Invalid",
			Error: fmt.Errorf("data source name cannot be empty"),
		}
	}

	switch source.Type {
	case dacv1alpha1.DataSourceMySQL:
		return h.checkMySQLStatus(ctx, source)
	case dacv1alpha1.DataSourcePostgres:
		return h.checkPostgresStatus(ctx, source)
	case dacv1alpha1.DataSourceMinIO:
		return h.checkMinIOStatus(ctx, source)
	case dacv1alpha1.DataSourceFileServer:
		return h.checkFileserverStatus(ctx, source)
	default:
		return SourceStatusResult{
			Name:  source.Name,
			Phase: "Unknown",
			Error: fmt.Errorf("unknown data source type: %s", source.Type),
		}
	}
}

// checkMySQLStatus checks MySQL data source status
func (h *DataDescriptorHandler) checkMySQLStatus(ctx context.Context, source dacv1alpha1.DataSource) SourceStatusResult {
	// Validate configuration
	host, ok := source.Metadata["host"]
	if !ok || host == "" {
		return SourceStatusResult{
			Name:  source.Name,
			Phase: "Invalid",
			Error: fmt.Errorf("MySQL host not configured in metadata"),
		}
	}

	return SourceStatusResult{
		Name:         source.Name,
		Phase:        "Ready",
		LastSyncTime: metav1.NewTime(time.Now()),
		Records:      5000,
	}
}

// checkPostgresStatus checks Postgres data source status
func (h *DataDescriptorHandler) checkPostgresStatus(ctx context.Context, source dacv1alpha1.DataSource) SourceStatusResult {
	// Validate configuration
	host, ok := source.Metadata["host"]
	if !ok || host == "" {
		return SourceStatusResult{
			Name:  source.Name,
			Phase: "Invalid",
			Error: fmt.Errorf("Postgres host not configured in metadata"),
		}
	}

	return SourceStatusResult{
		Name:         source.Name,
		Phase:        "Ready",
		LastSyncTime: metav1.NewTime(time.Now()),
		Records:      5000,
	}
}

// checkMinIOStatus checks MinIO data source status
func (h *DataDescriptorHandler) checkMinIOStatus(ctx context.Context, source dacv1alpha1.DataSource) SourceStatusResult {
	// Validate configuration
	host, ok := source.Metadata["host"]
	if !ok || host == "" {
		return SourceStatusResult{
			Name:  source.Name,
			Phase: "Invalid",
			Error: fmt.Errorf("MinIO host not configured in metadata"),
		}
	}

	return SourceStatusResult{
		Name:         source.Name,
		Phase:        "Ready",
		LastSyncTime: metav1.NewTime(time.Now()),
		Records:      200,
	}
}

// checkFileserverStatus checks Fileserver data source status
func (h *DataDescriptorHandler) checkFileserverStatus(ctx context.Context, source dacv1alpha1.DataSource) SourceStatusResult {
	// Validate configuration
	host, ok := source.Metadata["host"]
	if !ok || host == "" {
		return SourceStatusResult{
			Name:  source.Name,
			Phase: "Invalid",
			Error: fmt.Errorf("Fileserver host not configured in metadata"),
		}
	}

	return SourceStatusResult{
		Name:         source.Name,
		Phase:        "Ready",
		LastSyncTime: metav1.NewTime(time.Now()),
		Records:      200,
	}
}

// ─────────────────────────────────────────────────────────────────────────────
// Auto-create DAC when DataDescriptor becomes Ready
// ─────────────────────────────────────────────────────────────────────────────

const (
	// Annotation on the DataDescriptor indicating auto-DAC creation should be skipped.
	annotationSkipAutoDAC     = "dac.dac.io/skip-auto-dac"
	annotationSyncRequestedAt = "dac.dac.io/sync-requested-at"
	// Label applied to auto-created DAC resources.
	labelAutoCreated = "dac.dac.io/auto-created"
	// Label linking the DAC back to its source DataDescriptor (ds type).
	labelSourceDD = "dac.dac.io/source-dd"
	// Label linking the DAC back to its source Semantic Group (normal type).
	labelSourceGroup = "dac.dac.io/source-group"

	// ConfigMap that holds default settings for auto-created DACs.
	dacConfigMapName      = "dac-configuration"
	dacConfigMapNamespace = "dac"

	// Keys inside dac-configuration for default LLM model ConfigMap names.
	keyDefaultPlannerLLM = "default-planner-llm"
	keyDefaultExpertLLM  = "default-expert-llm"

	// Hardcoded fallback if dac-configuration is missing or the keys are not set.
	fallbackDefaultLLM = "llm-deepseek-v32"

	// Annotation storing the SHA-256 hash of the agent_card JSON used when the
	// normal (sg) DAC was created. Used to detect semantic-group updates.
	annotationAgentCardHash = "dac.dac.io/agent-card-hash"

	// JSON array of semantic group IDs this DD belongs to. Written when the DD
	// joins a group; kept until delete job completes so normal DAC sync does not
	// depend on live dd_group_relation rows.
	annotationSemanticGroupIDs = "dac.dac.io/semantic-group-ids"

	featureDeleteNormalDACSync = "delete_normal_dac_sync"
)

// ErrRequeueNeeded is returned by DoAddOrUpdate when a pending DAC replacement
// requires the controller to requeue the DataDescriptor after a longer interval.
var ErrRequeueNeeded = fmt.Errorf("requeue needed for pending DAC replacement")

// defaultModelSpec reads the default planner/expert LLM ConfigMap names from the
// dac-configuration ConfigMap. If the ConfigMap or keys are absent it falls back
// to the hardcoded default (llm-deepseek-v32).
func (h *DataDescriptorHandler) defaultModelSpec(ctx context.Context) dacv1alpha1.ModelSpec {
	logger := h.Logger

	cm := &corev1.ConfigMap{}
	err := h.Kubeclient.Get(ctx, client.ObjectKey{
		Name:      dacConfigMapName,
		Namespace: dacConfigMapNamespace,
	}, cm)
	if err != nil {
		logger.Info("dac-configuration ConfigMap not found, using fallback LLM defaults",
			"fallback", fallbackDefaultLLM, "error", err)
		return dacv1alpha1.ModelSpec{
			PlannerLLM: fallbackDefaultLLM,
			ExpertLLM:  fallbackDefaultLLM,
		}
	}

	plannerLLM := cm.Data[keyDefaultPlannerLLM]
	expertLLM := cm.Data[keyDefaultExpertLLM]

	if plannerLLM == "" {
		plannerLLM = fallbackDefaultLLM
		logger.Info("default-planner-llm not set in dac-configuration, using fallback", "fallback", fallbackDefaultLLM)
	}
	if expertLLM == "" {
		expertLLM = fallbackDefaultLLM
		logger.Info("default-expert-llm not set in dac-configuration, using fallback", "fallback", fallbackDefaultLLM)
	}

	logger.Info("Resolved default LLM models from dac-configuration",
		"plannerLLM", plannerLLM, "expertLLM", expertLLM)
	return dacv1alpha1.ModelSpec{
		PlannerLLM: plannerLLM,
		ExpertLLM:  expertLLM,
	}
}

// ensureAutoDAC creates a "ds" type DataAgentContainer for the DataDescriptor
// when its OverallPhase transitions to Ready. The operation is idempotent; if
// the DAC already exists (or the DD opted out via annotation), it is a no-op.
//
// The AgentCard (name, description, skills) is fetched from data-services
// via FingerprintSearchByDD — the agent_card was generated by the data-sinker
// LLM pipeline during data processing and stored alongside the fingerprint.
func (h *DataDescriptorHandler) ensureAutoDAC(ctx context.Context, dd *dacv1alpha1.DataDescriptor) error {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)

	// Allow users to opt out by setting annotation
	if dd.Annotations != nil && dd.Annotations[annotationSkipAutoDAC] == "true" {
		logger.Info("Skipping auto DAC creation (annotation opt-out)")
		return nil
	}

	// Idempotency: check whether ANY ds DAC already exists for this DD.
	// If exists and AgentCard changed (e.g. after re-sync), patch DAC to trigger Pod rebuild.
	allDACs := &dacv1alpha1.DataAgentContainerList{}
	if err := h.Kubeclient.List(ctx, allDACs, client.InNamespace(dd.Namespace)); err != nil {
		return fmt.Errorf("failed to list existing DACs for DD %s: %w", dd.Name, err)
	}
	var existingDSDAC *dacv1alpha1.DataAgentContainer
	for i := range allDACs.Items {
		dac := &allDACs.Items[i]
		if dac.Spec.DACType != "ds" {
			continue
		}
		for _, sel := range dac.Spec.DataPolicy.SourceNameSelector {
			if sel == dd.Name {
				existingDSDAC = dac
				break
			}
		}
		if existingDSDAC != nil {
			break
		}
	}
	if existingDSDAC != nil {
		agentCard, rawAgentCard, err := h.fetchAgentCardFromDataServices(ctx, dd)
		if err != nil {
			logger.Info("DS DAC exists but failed to fetch AgentCard for update check, skipping",
				"existingDAC", existingDSDAC.Name, "error", err)
			return nil
		}
		// Hash the raw agent_card string from data-services, not json.Marshal(struct).
		// Unmarshal drops unknown JSON keys; re-marshal can match even when the DB text changed.
		currentHash := agentCardHash(rawAgentCard)
		storedHash := ""
		if existingDSDAC.Annotations != nil {
			storedHash = existingDSDAC.Annotations[annotationAgentCardHash]
		}
		if storedHash != "" && storedHash == currentHash {
			logger.Info("ensureAutoDAC: DS DAC already exists with matching AgentCard hash, skipping",
				"feature", "ensureAutoDAC_noop",
				"existingDAC", existingDSDAC.Name)
			return nil
		}
		// AgentCard changed (re-sync updated semantic_domain): patch DAC to trigger Pod rebuild
		logger.Info("ensureAutoDAC: AgentCard hash changed; patching DS DAC to rebuild Pod (e.g. after re-sync)",
			"feature", "ensureAutoDAC_agentcard_patch",
			"existingDAC", existingDSDAC.Name, "oldHash", storedHash, "newHash", currentHash)
		suffix := ddDeterministicSuffix(dd.Namespace, dd.Name)
		agentCard.Name = fmt.Sprintf("%s-dd-%s", agentCard.Name, suffix)
		modified := existingDSDAC.DeepCopy()
		modified.Spec.AgentCard = agentCard
		if modified.Annotations == nil {
			modified.Annotations = make(map[string]string)
		}
		modified.Annotations[annotationAgentCardHash] = currentHash
		if err := h.Kubeclient.Patch(ctx, modified, client.MergeFrom(existingDSDAC)); err != nil {
			logger.Error(err, "Failed to patch DS DAC with new AgentCard")
			return fmt.Errorf("failed to patch DS DAC %s: %w", existingDSDAC.Name, err)
		}
		h.EventsCli.Normal(dd, "AutoDACUpdated",
			fmt.Sprintf("Updated DataAgentContainer %s with new AgentCard after re-sync", existingDSDAC.Name))
		return nil
	}

	// Fetch AgentCard from data-services (generated by LLM during data-sinker processing).
	// If semantic domain or agent_card does not exist, this is an error — we do NOT
	// generate a fallback card because the data-sinker pipeline must have completed
	// successfully for the DD to be Ready.
	agentCard, rawAgentCard, err := h.fetchAgentCardFromDataServices(ctx, dd)
	if err != nil {
		return fmt.Errorf("cannot auto-create DAC: %w", err)
	}
	logger.Info("AgentCard resolved for auto DAC",
		"agentName", agentCard.Name,
		"skillsCount", len(agentCard.Skills))

	// Hash raw agent_card text from data-services (before name suffix) for change detection
	agentCardHashVal := agentCardHash(rawAgentCard)

	// DAC name format: <AgentCardName>-dd-<hash8>
	// e.g. bankbusinessanalyticsagent-dd-a1b2c3d4
	// Kubernetes names must be lowercase RFC-1123 compliant.
	// The suffix is a deterministic SHA-256 hash of dd.Namespace/dd.Name so that
	// the semantic-group expert agent can reconstruct it during agent matching
	// without extra metadata lookups.
	suffix := ddDeterministicSuffix(dd.Namespace, dd.Name)
	dacName := fmt.Sprintf("%s-dd-%s", sanitizeK8sName(agentCard.Name), suffix)
	agentCard.Name = fmt.Sprintf("%s-dd-%s", agentCard.Name, suffix)

	// Determine orchestratorAgentMaxLoops and expertAgentMaxSteps based on descriptorType.
	//   structured-xxx (e.g. structured-mysql, structured-postgres) → loops=2, steps=3
	//   code                                                        → loops=1, steps=1
	//   unstructured                                                 → loops=1, steps=1
	maxLoops, maxSteps := resolveAgentLimits(dd.Spec.DescriptorType)
	logger.Info("Resolved agent limits from descriptorType",
		"descriptorType", dd.Spec.DescriptorType,
		"orchestratorAgentMaxLoops", maxLoops,
		"expertAgentMaxSteps", maxSteps)

	// Read default LLM model names from dac-configuration ConfigMap.
	modelSpec := h.defaultModelSpec(ctx)

	dac := &dacv1alpha1.DataAgentContainer{
		TypeMeta: metav1.TypeMeta{
			APIVersion: "dac.dac.io/v1alpha1",
			Kind:       "DataAgentContainer",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:      dacName,
			Namespace: dd.Namespace,
			Labels: map[string]string{
				labelAutoCreated: "true",
				labelSourceDD:    dd.Name,
			},
			Annotations: map[string]string{
				annotationAgentCardHash: agentCardHashVal,
			},
		},
		Spec: dacv1alpha1.DataAgentContainerSpec{
			DACType: "ds",
			DataPolicy: dacv1alpha1.DataPolicy{
				DataSourceType:     "SemanticDomain",
				SourceNameSelector: []string{dd.Name},
			},
			AgentCard:                 agentCard,
			Model:                     modelSpec,
			OrchestratorAgentMaxLoops: maxLoops,
			ExpertAgentMaxSteps:       maxSteps,
		},
	}

	if err := h.Kubeclient.Create(ctx, dac); err != nil {
		if apierrors.IsAlreadyExists(err) {
			logger.Info("Auto DAC name collision, skipping (will retry on next reconcile)", "dac", dacName)
			return nil
		}
		return fmt.Errorf("failed to create auto DAC %s: %w", dacName, err)
	}

	logger.Info("Auto DAC created successfully", "dac", dacName,
		"agentName", agentCard.Name,
		"descriptorType", dd.Spec.DescriptorType,
		"plannerLLM", modelSpec.PlannerLLM,
		"expertLLM", modelSpec.ExpertLLM,
		"orchestratorAgentMaxLoops", maxLoops,
		"expertAgentMaxSteps", maxSteps)
	h.EventsCli.Normal(dd, "AutoDACCreated",
		fmt.Sprintf("Automatically created DataAgentContainer %s (ds type, agent=%s, planner=%s, expert=%s, loops=%s, steps=%s)",
			dacName, agentCard.Name, modelSpec.PlannerLLM, modelSpec.ExpertLLM, maxLoops, maxSteps))
	return nil
}

// randomSuffix generates a cryptographically random hex string of the given length.
func randomSuffix(length int) string {
	b := make([]byte, (length+1)/2)
	if _, err := rand.Read(b); err != nil {
		// Extremely unlikely; fall back to timestamp-based suffix
		return fmt.Sprintf("%08x", time.Now().UnixNano()&0xFFFFFFFF)
	}
	return hex.EncodeToString(b)[:length]
}

// ddDeterministicSuffix returns an 8-character hex string derived from the
// SHA-256 hash of "namespace/name". This makes the DD→agent name mapping
// predictable so that the semantic-group expert agent can reconstruct the
// registered agent name from (dd_namespace, dd_name) without extra lookups.
func ddDeterministicSuffix(namespace, name string) string {
	h := sha256.Sum256([]byte(namespace + "/" + name))
	return hex.EncodeToString(h[:])[:8]
}

// resolveAgentLimits returns (orchestratorAgentMaxLoops, expertAgentMaxSteps)
// based on the DataDescriptor's descriptorType:
//
//	structured-xxx  (e.g. structured-mysql, structured-postgres, …) → "2", "3"
//	code                                                             → "1", "1"
//	unstructured                                                     → "1", "1"
//	(unknown)                                                        → "1", "1"
func resolveAgentLimits(descriptorType string) (maxLoops string, maxSteps string) {
	dt := strings.ToLower(descriptorType)
	if strings.HasPrefix(dt, "structured") {
		return "0", "1"
	}
	// code, unstructured, or anything else
	return "1", "1"
}

// sanitizeK8sName converts a name to a valid lowercase Kubernetes RFC-1123 name fragment.
func sanitizeK8sName(name string) string {
	base := strings.ToLower(name)
	var clean strings.Builder
	for _, ch := range base {
		if (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '-' {
			clean.WriteRune(ch)
		}
	}
	return strings.Trim(clean.String(), "-")
}

// agentCardHash returns the hex-encoded SHA-256 digest of the agent_card payload.
// For ds DACs this must be the raw string from data-services (same bytes as stored in
// semantic_domain.agent_card), not json.Marshal of the parsed AgentCard struct.
func agentCardHash(agentCardJSON string) string {
	h := sha256.Sum256([]byte(agentCardJSON))
	return hex.EncodeToString(h[:])
}

// isDACHealthy returns true when the DAC has a status condition
// Type=Available with Status=True, meaning its deployment is up and the
// agent responded to the health probe.
func isDACHealthy(dac *dacv1alpha1.DataAgentContainer) bool {
	for _, c := range dac.Status.Conditions {
		if c.Type == dacv1alpha1.ConditionAvailable && c.Status == corev1.ConditionTrue {
			return true
		}
	}
	return false
}

// expandGroupIDsWithAncestors expands seed semantic group IDs to include all
// ancestor groups by following parent_id links from data-services.
//
// It is best-effort and tolerant to partial failures:
// - a single group lookup failure only skips that branch
// - loops are prevented by "expanded" dedupe
// - a maximum chain depth guard avoids pathological data
func (h *DataDescriptorHandler) expandGroupIDsWithAncestors(ctx context.Context, seedGroupIDs map[string]bool) map[string]bool {
	expanded := map[string]bool{}
	if len(seedGroupIDs) == 0 {
		return expanded
	}
	if h.HTTPClient == nil {
		for gid := range seedGroupIDs {
			trimmed := strings.TrimSpace(gid)
			if trimmed != "" {
				expanded[trimmed] = true
			}
		}
		return expanded
	}

	logger := h.Logger
	const maxAncestorDepth = 10

	for seedID := range seedGroupIDs {
		current := strings.TrimSpace(seedID)
		depth := 0

		for current != "" {
			if expanded[current] {
				break
			}
			expanded[current] = true

			if depth >= maxAncestorDepth {
				logger.Info("Hit semantic group ancestor depth limit, stop climbing",
					"groupID", current, "maxDepth", maxAncestorDepth)
				break
			}

			groupResp, err := h.HTTPClient.GetSemanticGroupByID(ctx, current)
			if err != nil {
				logger.Error(err, "Failed to fetch semantic group while expanding ancestors",
					"groupID", current)
				break
			}

			parentID := strings.TrimSpace(groupResp.Data.ParentID)
			if parentID == "" {
				break
			}
			if parentID == current {
				logger.Info("Detected self-parent semantic group, stop climbing",
					"groupID", current)
				break
			}

			current = parentID
			depth++
		}
	}

	logger.Info("Expanded semantic groups with ancestors",
		"seedCount", len(seedGroupIDs), "expandedCount", len(expanded))
	return expanded
}

// ─────────────────────────────────────────────────────────────────────────────
// Auto-create "normal" DAC for Semantic Groups
// ─────────────────────────────────────────────────────────────────────────────

// ensureAutoNormalDAC ensures that every semantic group associated with this
// DataDescriptor has an up-to-date "normal" type DAC.
//
// When a group's agent_card has changed (detected via SHA-256 hash stored in
// the annotation dac.dac.io/agent-card-hash), a blue-green replacement is
// performed: a new DAC is created first; once it becomes healthy the old DAC
// is deleted. This avoids downtime for the agent.
//
// The function returns needsRequeue=true when a newly-created or
// not-yet-healthy replacement DAC exists, signalling the controller to
// reconcile again after a delay.
func (h *DataDescriptorHandler) ensureAutoNormalDAC(ctx context.Context, dd *dacv1alpha1.DataDescriptor) (needsRequeue bool, err error) {
	if dd.Annotations != nil && dd.Annotations[annotationSkipAutoDAC] == "true" {
		return false, nil
	}
	if h.HTTPClient == nil {
		h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name).
			Info("HTTPClient not configured, skipping normal DAC creation")
		return false, nil
	}

	groupIDs, err := h.collectSemanticGroupIDsForDD(ctx, dd)
	if err != nil {
		return false, err
	}
	if len(groupIDs) == 0 {
		return false, nil
	}
	if err := h.persistSemanticGroupIDs(ctx, dd.Namespace, dd.Name, groupIDs); err != nil {
		h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name).
			Error(err, "Failed to persist semantic-group-ids on DD")
	}
	return h.ensureNormalDACForGroups(ctx, dd, groupIDs)
}

func (h *DataDescriptorHandler) collectSemanticGroupIDsForDD(ctx context.Context, dd *dacv1alpha1.DataDescriptor) (map[string]bool, error) {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)

	sdResp, err := h.HTTPClient.SemanticDomainSearchByDD(ctx, &apiclient.SemanticDomainSearchByDDRequest{
		DdNamespace: dd.Namespace,
		DdName:      dd.Name,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to fetch semantic domains for DD %s/%s: %w", dd.Namespace, dd.Name, err)
	}
	if sdResp == nil || len(sdResp.Data) == 0 {
		logger.Info("No semantic domains found, skipping normal DAC group collection")
		return nil, nil
	}

	groupIDs := map[string]bool{}
	for _, sd := range sdResp.Data {
		if sd.SemanticDomainID == "" {
			continue
		}
		relResp, err := h.HTTPClient.GetRelationsBySDID(ctx, sd.SemanticDomainID)
		if err != nil {
			logger.Error(err, "Failed to fetch group relations for semantic domain",
				"sdID", sd.SemanticDomainID)
			continue
		}
		for _, rel := range relResp.Data {
			if rel.GroupID != "" {
				groupIDs[rel.GroupID] = true
			}
		}
	}
	if len(groupIDs) == 0 {
		logger.Info("Semantic domains have no group memberships, skipping normal DAC group collection")
		return nil, nil
	}

	groupIDs = h.expandGroupIDsWithAncestors(ctx, groupIDs)
	if len(groupIDs) == 0 {
		logger.Info("No semantic groups remain after ancestor expansion, skipping normal DAC group collection")
		return nil, nil
	}
	return groupIDs, nil
}

func (h *DataDescriptorHandler) semanticGroupIDsFromAnnotations(dd *dacv1alpha1.DataDescriptor) map[string]bool {
	groupIDs := map[string]bool{}
	if dd.Annotations == nil {
		return groupIDs
	}

	raw := strings.TrimSpace(dd.Annotations[annotationSemanticGroupIDs])
	if raw == "" {
		return groupIDs
	}

	var groupIDList []string
	if err := json.Unmarshal([]byte(raw), &groupIDList); err != nil {
		h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name).
			Error(err, "Invalid semantic-group-ids annotation",
				"feature", featureDeleteNormalDACSync,
				"step", "invalid_semantic_group_ids_annotation",
				"semanticGroupIDsAnnotation", raw)
		return groupIDs
	}
	for _, id := range groupIDList {
		if id != "" {
			groupIDs[id] = true
		}
	}
	return groupIDs
}

func groupIDMapKeys(groupIDs map[string]bool) []string {
	if len(groupIDs) == 0 {
		return nil
	}
	ids := make([]string, 0, len(groupIDs))
	for id := range groupIDs {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

func semanticGroupIDsAnnotationRaw(dd *dacv1alpha1.DataDescriptor) string {
	if dd.Annotations == nil {
		return ""
	}
	return strings.TrimSpace(dd.Annotations[annotationSemanticGroupIDs])
}

func (h *DataDescriptorHandler) persistSemanticGroupIDs(ctx context.Context, namespace, name string, groupIDs map[string]bool) error {
	if len(groupIDs) == 0 {
		return nil
	}

	latest := &dacv1alpha1.DataDescriptor{}
	if err := h.Kubeclient.Get(ctx, types.NamespacedName{Namespace: namespace, Name: name}, latest); err != nil {
		return fmt.Errorf("get DataDescriptor before persisting semantic-group-ids: %w", err)
	}

	merged := h.semanticGroupIDsFromAnnotations(latest)
	for id := range groupIDs {
		merged[id] = true
	}

	ids := make([]string, 0, len(merged))
	for id := range merged {
		ids = append(ids, id)
	}
	sort.Strings(ids)

	encoded, err := json.Marshal(ids)
	if err != nil {
		return fmt.Errorf("marshal semantic-group-ids: %w", err)
	}

	if latest.Annotations == nil {
		latest.Annotations = make(map[string]string)
	}
	latest.Annotations[annotationSemanticGroupIDs] = string(encoded)

	if err := h.Kubeclient.Update(ctx, latest); err != nil {
		return fmt.Errorf("set semantic-group-ids annotation: %w", err)
	}

	h.Logger.WithValues("namespace", namespace, "name", name).
		Info("Persisted semantic-group-ids on DD", "feature", "dd_semantic_group_ids",
			"step", "persisted", "groupCount", len(ids), "groupIDs", ids)
	return nil
}

func (h *DataDescriptorHandler) clearSemanticGroupIDsByName(ctx context.Context, namespace, name string) error {
	latest := &dacv1alpha1.DataDescriptor{}
	if err := h.Kubeclient.Get(ctx, types.NamespacedName{Namespace: namespace, Name: name}, latest); err != nil {
		return err
	}
	if latest.Annotations == nil || latest.Annotations[annotationSemanticGroupIDs] == "" {
		return nil
	}
	delete(latest.Annotations, annotationSemanticGroupIDs)
	return h.Kubeclient.Update(ctx, latest)
}

// EnsureNormalDACAfterDelete runs ensureNormalDACForGroups for groups recorded
// on the deleting DD (dac.dac.io/semantic-group-ids). Call only after delete
// job success; hash comparison inside ensureNormalDACForGroups decides action.
func (h *DataDescriptorHandler) EnsureNormalDACAfterDelete(ctx context.Context, namespace, name string) (needsRequeue bool, err error) {
	logger := h.Logger.WithValues("namespace", namespace, "name", name)

	logger.Info("EnsureNormalDACAfterDelete invoked (reads DD annotation before finalizer removal)",
		"feature", featureDeleteNormalDACSync,
		"step", "begin")

	dd := &dacv1alpha1.DataDescriptor{}
	if err := h.Kubeclient.Get(ctx, types.NamespacedName{Namespace: namespace, Name: name}, dd); err != nil {
		if apierrors.IsNotFound(err) {
			logger.Info("DataDescriptor gone before normal DAC sync after delete, skipping",
				"feature", featureDeleteNormalDACSync,
				"step", "skip_dd_not_found")
			return false, nil
		}
		return false, fmt.Errorf("get DataDescriptor for normal DAC sync after delete: %w", err)
	}

	logger = logger.WithValues("ddUID", dd.UID)
	rawAnnotation := semanticGroupIDsAnnotationRaw(dd)
	logger.Info("Loaded deleting DD for normal DAC sync after delete",
		"feature", featureDeleteNormalDACSync,
		"step", "dd_loaded",
		"semanticGroupIDsAnnotation", rawAnnotation,
		"deletionTimestamp", dd.DeletionTimestamp)

	if dd.Annotations != nil && dd.Annotations[annotationSkipAutoDAC] == "true" {
		logger.Info("Skipping normal DAC sync after delete (dac.dac.io/skip-auto-dac=true)",
			"feature", featureDeleteNormalDACSync,
			"step", "skip_auto_dac_opt_out")
		return false, nil
	}
	if h.HTTPClient == nil {
		logger.Info("Skipping normal DAC sync after delete (HTTPClient not configured)",
			"feature", featureDeleteNormalDACSync,
			"step", "skip_no_http_client")
		return false, nil
	}
	if dd.Annotations == nil {
		logger.Info("Skipping normal DAC sync after delete: DD has no annotations",
			"feature", featureDeleteNormalDACSync,
			"step", "skip_no_annotations",
			"hint", "expected dac.dac.io/semantic-group-ids to be set when DD joined a semantic group")
		return false, nil
	}

	groupIDs := h.semanticGroupIDsFromAnnotations(dd)
	if len(groupIDs) == 0 {
		logger.Info("Skipping normal DAC sync after delete: dac.dac.io/semantic-group-ids is empty or missing",
			"feature", featureDeleteNormalDACSync,
			"step", "skip_no_semantic_group_ids",
			"semanticGroupIDsAnnotation", rawAnnotation,
			"hint", "write annotation on group join (semantic-grouper AddOrUpdate) or Ready reconcile (ensureAutoNormalDAC); live dd_group_relation is not used here")
		return false, nil
	}

	seedGroupIDs := groupIDMapKeys(groupIDs)
	groupIDs = h.expandGroupIDsWithAncestors(ctx, groupIDs)
	if len(groupIDs) == 0 {
		logger.Info("Skipping normal DAC sync after delete: no semantic groups after ancestor expansion",
			"feature", featureDeleteNormalDACSync,
			"step", "skip_empty_after_ancestor_expand",
			"seedGroupIDs", seedGroupIDs)
		return false, nil
	}

	expandedGroupIDs := groupIDMapKeys(groupIDs)
	logger.Info("Running ensureNormalDACForGroups after DD delete",
		"feature", featureDeleteNormalDACSync,
		"step", "ensure_normal_dac",
		"seedGroupCount", len(seedGroupIDs),
		"seedGroupIDs", seedGroupIDs,
		"expandedGroupCount", len(expandedGroupIDs),
		"expandedGroupIDs", expandedGroupIDs)

	needsRequeue, err = h.ensureNormalDACForGroups(ctx, dd, groupIDs)
	if err != nil {
		logger.Error(err, "ensureNormalDACForGroups failed after DD delete",
			"feature", featureDeleteNormalDACSync,
			"step", "ensure_normal_dac_error",
			"needsRequeue", needsRequeue)
		return needsRequeue, err
	}

	if needsRequeue {
		logger.Info("Normal DAC blue-green still in progress after DD delete, will requeue",
			"feature", featureDeleteNormalDACSync,
			"step", "needs_requeue")
	} else {
		logger.Info("Normal DAC sync after DD delete completed (no requeue)",
			"feature", featureDeleteNormalDACSync,
			"step", "done",
			"groupIDs", expandedGroupIDs)
	}
	// Do not clear semantic-group-ids here: the DD is about to lose its finalizer
	// and be deleted. An extra Update races with finalizer removal in the controller.
	return needsRequeue, nil
}

func (h *DataDescriptorHandler) ensureNormalDACForGroups(ctx context.Context, dd *dacv1alpha1.DataDescriptor, groupIDs map[string]bool) (needsRequeue bool, err error) {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)

	if len(groupIDs) == 0 {
		return false, nil
	}

	// List ALL existing DACs in the namespace.
	// Build a map: groupID -> []*DAC  (there may be >1 during blue-green)
	allDACs := &dacv1alpha1.DataAgentContainerList{}
	if err := h.Kubeclient.List(ctx, allDACs, client.InNamespace(dd.Namespace)); err != nil {
		return false, fmt.Errorf("failed to list existing DACs in namespace %s: %w", dd.Namespace, err)
	}

	type dacInfo struct {
		dac  dacv1alpha1.DataAgentContainer
		hash string // annotation hash, may be empty for legacy/manual DACs
	}
	dacsByGroup := map[string][]dacInfo{} // groupID -> []dacInfo
	for _, dac := range allDACs.Items {
		if gid := dac.Spec.DataPolicy.SemanticGroupID; gid != "" {
			hash := ""
			if dac.Annotations != nil {
				hash = dac.Annotations[annotationAgentCardHash]
			}
			dacsByGroup[gid] = append(dacsByGroup[gid], dacInfo{dac: dac, hash: hash})
		}
	}

	// For each group, ensure an up-to-date DAC exists (blue-green).
	modelSpec := h.defaultModelSpec(ctx)

	for groupID := range groupIDs {
		// Fetch group details to get the latest agent_card.
		groupResp, err := h.HTTPClient.GetSemanticGroupByID(ctx, groupID)
		if err != nil {
			logger.Error(err, "Failed to fetch semantic group, skipping",
				"groupID", groupID)
			continue
		}
		if groupResp.Data.AgentCard == "" {
			logger.Info("Semantic group has no agent_card, skipping",
				"groupID", groupID, "groupName", groupResp.Data.GroupName)
			continue
		}

		currentHash := agentCardHash(groupResp.Data.AgentCard)
		existing := dacsByGroup[groupID]

		// Classify existing DACs into "current" (hash matches) and "stale".
		var currentDACs, staleDACs []dacInfo
		for _, di := range existing {
			if di.hash == currentHash {
				currentDACs = append(currentDACs, di)
			} else {
				staleDACs = append(staleDACs, di)
			}
		}

		// Case A: A DAC with the current hash already exists.
		if len(currentDACs) > 0 {
			currentDAC := currentDACs[0]
			if len(staleDACs) == 0 {
				logger.Info("Semantic group agent_card unchanged, skipping normal DAC replacement",
					"groupID", groupID, "agentCardHash", currentHash)
			}
			if isDACHealthy(&currentDAC.dac) {
				// New DAC is healthy — clean up any stale DACs.
				for _, stale := range staleDACs {
					logger.Info("Deleting stale normal DAC after blue-green replacement",
						"staleDAC", stale.dac.Name, "groupID", groupID,
						"replacedBy", currentDAC.dac.Name)
					if err := h.Kubeclient.Delete(ctx, &stale.dac); err != nil && !apierrors.IsNotFound(err) {
						logger.Error(err, "Failed to delete stale DAC",
							"staleDAC", stale.dac.Name)
					} else {
						h.EventsCli.Normal(dd, "StaleNormalDACDeleted",
							fmt.Sprintf("Deleted stale normal DAC %s (replaced by %s) for group %s",
								stale.dac.Name, currentDAC.dac.Name, groupID))
					}
				}
			} else {
				// New DAC exists but is not healthy yet — requeue.
				logger.Info("Replacement normal DAC not yet healthy, will requeue",
					"dac", currentDAC.dac.Name, "groupID", groupID)
				needsRequeue = true
			}
			continue
		}

		// Case B: No DAC with the current hash. If there are stale DACs this
		// is an update; if none, it is a fresh creation.
		if len(staleDACs) > 0 {
			logger.Info("Semantic group agent_card changed, starting blue-green replacement",
				"groupID", groupID, "oldHash", staleDACs[0].hash, "newHash", currentHash)
		}

		// Parse the group's agent_card to build the DAC spec.
		var a2a a2aAgentCard
		if err := json.Unmarshal([]byte(groupResp.Data.AgentCard), &a2a); err != nil {
			logger.Error(err, "Failed to parse agent_card from semantic group, skipping",
				"groupID", groupID)
			continue
		}
		if a2a.Name == "" {
			logger.Info("Semantic group agent_card has empty name, skipping",
				"groupID", groupID)
			continue
		}

		skills := make([]dacv1alpha1.AgentSkill, 0, len(a2a.Skills))
		for _, s := range a2a.Skills {
			skills = append(skills, dacv1alpha1.AgentSkill{
				ID:          s.ID,
				Name:        s.Name,
				Description: s.Description,
				Tags:        s.Tags,
				Examples:    s.Examples,
			})
		}

		sgSuffix := randomSuffix(8)
		agentCard := dacv1alpha1.AgentCard{
			Name:        fmt.Sprintf("%s-sg-%s", a2a.Name, sgSuffix),
			Description: a2a.Description,
			Skills:      skills,
		}
		dacName := fmt.Sprintf("%s-sg-%s", sanitizeK8sName(a2a.Name), sgSuffix)

		dac := &dacv1alpha1.DataAgentContainer{
			TypeMeta: metav1.TypeMeta{
				APIVersion: "dac.dac.io/v1alpha1",
				Kind:       "DataAgentContainer",
			},
			ObjectMeta: metav1.ObjectMeta{
				Name:      dacName,
				Namespace: dd.Namespace,
				Labels: map[string]string{
					labelAutoCreated: "true",
					labelSourceGroup: groupID,
				},
				Annotations: map[string]string{
					annotationAgentCardHash: currentHash,
				},
			},
			Spec: dacv1alpha1.DataAgentContainerSpec{
				DACType: "normal",
				DataPolicy: dacv1alpha1.DataPolicy{
					DataSourceType:  "SemanticGroup",
					SemanticGroupID: groupID,
				},
				AgentCard:                 agentCard,
				Model:                     modelSpec,
				OrchestratorAgentMaxLoops: "1",
				ExpertAgentMaxSteps:       "1",
			},
		}

		if err := h.Kubeclient.Create(ctx, dac); err != nil {
			if apierrors.IsAlreadyExists(err) {
				logger.Info("Normal DAC name collision, skipping (will retry on next reconcile)",
					"dac", dacName, "groupID", groupID)
				needsRequeue = true
				continue
			}
			logger.Error(err, "Failed to create normal DAC for semantic group",
				"dac", dacName, "groupID", groupID)
			continue
		}

		logger.Info("Normal DAC created successfully",
			"dac", dacName,
			"groupID", groupID,
			"agentName", a2a.Name,
			"agentCardHash", currentHash,
			"plannerLLM", modelSpec.PlannerLLM,
			"expertLLM", modelSpec.ExpertLLM)
		h.EventsCli.Normal(dd, "AutoNormalDACCreated",
			fmt.Sprintf("Automatically created normal DataAgentContainer %s (group=%s, agent=%s, hash=%s, planner=%s, expert=%s)",
				dacName, groupID, a2a.Name, currentHash[:12], modelSpec.PlannerLLM, modelSpec.ExpertLLM))
		needsRequeue = true
	}

	return needsRequeue, nil
}

// a2aAgentCard mirrors the JSON structure produced by the data-sinker LLM pipeline.
type a2aAgentCard struct {
	Name        string          `json:"name"`
	Description string          `json:"description"`
	Skills      []a2aAgentSkill `json:"skills"`
}

type a2aAgentSkill struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Tags        []string `json:"tags"`
	Examples    []string `json:"examples"`
}

// fetchAgentCardFromDataServices queries the central data-services for
// the semantic domain records associated with the DataDescriptor and extracts
// the LLM-generated agent_card.
//
// API: POST /semantic_domains/search/by-dd
// The agent_card field is a JSON string produced by the data-sinker LLM pipeline.
//
// Returns an error if:
//   - HTTPClient is not configured
//   - the data-services query fails
//   - no semantic domain exists for this DD
//   - none of the semantic domains has a valid agent_card
//
// The second return value is the raw agent_card string from data-services for that record;
// callers should hash it for dac.dac.io/agent-card-hash (not json.Marshal of the struct).
func (h *DataDescriptorHandler) fetchAgentCardFromDataServices(ctx context.Context, dd *dacv1alpha1.DataDescriptor) (dacv1alpha1.AgentCard, string, error) {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)

	if h.HTTPClient == nil {
		return dacv1alpha1.AgentCard{}, "", fmt.Errorf("HTTPClient not configured, cannot fetch agent_card from data-services")
	}

	resp, err := h.HTTPClient.SemanticDomainSearchByDD(ctx, &apiclient.SemanticDomainSearchByDDRequest{
		DdNamespace: dd.Namespace,
		DdName:      dd.Name,
	})
	if err != nil {
		return dacv1alpha1.AgentCard{}, "", fmt.Errorf("failed to query data-services for semantic domains: %w", err)
	}

	if resp == nil || len(resp.Data) == 0 {
		return dacv1alpha1.AgentCard{}, "", fmt.Errorf(
			"no semantic domain found in data-services for DD %s/%s — "+
				"data-sinker may not have completed agent_card generation",
			dd.Namespace, dd.Name)
	}

	// Use the first semantic domain that has a valid, parseable agent_card
	var lastParseErr error
	for _, sd := range resp.Data {
		if sd.AgentCard == "" {
			continue
		}

		raw := sd.AgentCard
		var a2a a2aAgentCard
		if err := json.Unmarshal([]byte(raw), &a2a); err != nil {
			logger.Error(err, "Failed to parse agent_card JSON, trying next semantic domain",
				"semanticDomainID", sd.SemanticDomainID)
			lastParseErr = err
			continue
		}

		if a2a.Name == "" {
			lastParseErr = fmt.Errorf("agent_card name is empty in semantic domain %s", sd.SemanticDomainID)
			continue
		}

		// Map A2A skills → DAC AgentSkill
		skills := make([]dacv1alpha1.AgentSkill, 0, len(a2a.Skills))
		for _, s := range a2a.Skills {
			skills = append(skills, dacv1alpha1.AgentSkill{
				ID:          s.ID,
				Name:        s.Name,
				Description: s.Description,
				Tags:        s.Tags,
				Examples:    s.Examples,
			})
		}

		logger.Info("Successfully fetched AgentCard from semantic domain",
			"agentName", a2a.Name,
			"skillsCount", len(skills),
			"semanticDomainID", sd.SemanticDomainID)

		return dacv1alpha1.AgentCard{
			Name:        a2a.Name,
			Description: a2a.Description,
			Skills:      skills,
		}, raw, nil
	}

	// All semantic domains existed but none had a valid agent_card
	if lastParseErr != nil {
		return dacv1alpha1.AgentCard{}, "", fmt.Errorf(
			"semantic domains exist for DD %s/%s but none has a valid agent_card: %w",
			dd.Namespace, dd.Name, lastParseErr)
	}
	return dacv1alpha1.AgentCard{}, "", fmt.Errorf(
		"semantic domains exist for DD %s/%s but all agent_card fields are empty",
		dd.Namespace, dd.Name)
}

// get prompts from configmap
func (h *DataDescriptorHandler) getFewshotsAndBackgroudKnowledgeFromConfigmap(ctx context.Context, dd *dacv1alpha1.DataDescriptor, promptConfigmapName string) (*dacv1alpha1.ConfigMapData, error) {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("getFewshotsAndBackgroudKnowledgeFromConfigmap, promptConfigmapName", "promptConfigmapName", promptConfigmapName)

	if promptConfigmapName == "" {
		return nil, nil
	}

	configMapName := promptConfigmapName
	configMap, err := h.K8sServices.GetConfigMap(dd.Namespace, configMapName)
	if err != nil {
		return nil, fmt.Errorf("failed to get configmap %s/%s: %v", dd.Namespace, configMapName, err)
	}

	var fewShots []dacv1alpha1.FewShot
	if fewshotsData, exists := configMap.Data["fewshots.json"]; exists && fewshotsData != "" {
		if err := json.Unmarshal([]byte(fewshotsData), &fewShots); err != nil {
			return nil, fmt.Errorf("failed to parse fewshots.json in configmap %s: %v", configMapName, err)
		}
	}
	logger.Info("fewshots", "fewshots.json", fewShots)

	var backgroundKnowledge []dacv1alpha1.BackgroundKnowledge
	if bgData, exists := configMap.Data["background_knowledge.json"]; exists && bgData != "" {
		if err := json.Unmarshal([]byte(bgData), &backgroundKnowledge); err != nil {
			return nil, fmt.Errorf("failed to parse background_knowledge.json in configmap %s: %v", configMapName, err)
		}
	}
	logger.Info("backgroundKnowledge", "background_knowledge.json", backgroundKnowledge)

	return &dacv1alpha1.ConfigMapData{
		FewShots:            fewShots,
		BackgroundKnowledge: backgroundKnowledge,
	}, nil
}
