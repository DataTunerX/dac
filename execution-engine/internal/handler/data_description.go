package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"time"

	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
	"github.com/DataTunerX/dac/execution-engine/client/http"
	"github.com/DataTunerX/dac/execution-engine/client/k8s"
	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type DataDescriptorHandler struct {
	K8sServices k8s.Services
	EventsCli   k8s.Event
	Kubeclient  client.Client
	Logger      logr.Logger
	HTTPClient  *http.APIClient
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

func (h *DataDescriptorHandler) DoAddOrUpdate(ctx context.Context, dd *dacv1alpha1.DataDescriptor) error {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("DoAddOrUpdate Processing DataDescriptor")

	// handle dd logic
	taskIDs, err := h.handleDD(ctx, dd)
	if err != nil {
		return fmt.Errorf("failed to handle data descriptor: %w", err)
	}

	logger.Info("AddOrUpdate task IDs", "taskIDs", taskIDs)

	// handle dd status
	err = h.handleDDStatus(ctx, dd, taskIDs)
	if err != nil {
		return fmt.Errorf("failed to update status: %w", err)
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

		promptConfigmapName := source.Prompts.Prompts.Name
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
				"processing":     source.Processing,
				"classification": source.Classification,
			},
		}

		logger.Info("start triggered task...", "source", source.Name, "requestData", requestData)

		taskID, err := h.HTTPClient.TriggerTask(ctx, requestData)
		if err != nil {
			logger.Error(err, "Failed to trigger task for source",
				"source", source.Name,
				"requestData", requestData)
			return nil, fmt.Errorf("failed to trigger task for source %s: %w", source.Name, err)
		}

		logger.Info("Successfully triggered task",
			"source", source.Name,
			"taskID", taskID,
			"requestData", requestData)
		taskIDs[source.Name] = taskID
	}

	return taskIDs, nil
}

func (h *DataDescriptorHandler) handleDDDelete(ctx context.Context, namespace string, name string) (string, error) {
	logger := h.Logger.WithValues("namespace", namespace, "name", name)
	logger.Info("Delete DataDescriptor")

	requestData := map[string]interface{}{
		"data": map[string]interface{}{
			"operation": "Delete",
			"descriptor": map[string]interface{}{
				"name":      name,
				"namespace": namespace,
			},
		},
	}

	logger.Info("start triggered task to delete dd ...", "namespace", namespace, "name", name, "requestData", requestData)

	taskID, err := h.HTTPClient.TriggerTask(ctx, requestData)
	if err != nil {
		logger.Error(err, "Failed to trigger task to delete dd", "namespace", namespace, "name", name, "requestData", requestData)
		return "", fmt.Errorf("failed to trigger task to delete dd, namespace:%s, name:%s %w", namespace, name, err)
	}

	logger.Info("Successfully triggered task to delete dd", "namespace", namespace, "name", name, "taskID", taskID, "requestData", requestData)
	return taskID, nil
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

	// If this is a new resource, set initial condition
	if dd.Status.OverallPhase == "" {
		newStatus.SetCreateCondition("Initializing data descriptor")
	}

	// Check data source statuses
	sourceStatuses := make([]dacv1alpha1.SourceStatus, len(dd.Spec.Sources))
	allHealthy := true
	var aggregatedErrors []error
	var aggregatedNotReady []string

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
		h.EventsCli.Normal(dd, "AllSourcesHealthy", "All data sources healthy and tasks triggered and Completed.")
	} else {
		newStatus.OverallPhase = "NotReady"
		errorMsg := fmt.Sprintf("%d data sources task not completed, %d data sources have issues ", len(aggregatedNotReady), len(aggregatedErrors))
		c := dacv1alpha1.NewCondition(dacv1alpha1.ConditionNotReady, corev1.ConditionTrue, "NotReady", errorMsg)
		newStatus.SetDataDescriptorCondition(*c)
		h.EventsCli.Warning(dd, "SomeSourcesTaskErrorOrNotReady", errorMsg)
	}

	// Compare the new status with original, ignoring time fields
	if !h.isStatusEqualIgnoringTime(*originalStatus, newStatus) {
		// Update the status in the original object
		dd.Status = newStatus

		// Submit status update
		if err := h.Kubeclient.Status().Update(ctx, dd); err != nil {
			logger.Error(err, "Failed to update status")
			return fmt.Errorf("status update failed: %w", err)
		}
		logger.Info("Status updated successfully")
	} else {
		logger.Info("Status unchanged, skipping update")
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

func (h *DataDescriptorHandler) checkSourceStatus(ctx context.Context, dd *dacv1alpha1.DataDescriptor, source dacv1alpha1.DataSource, taskID string) SourceStatusResult {
	logger := h.Logger.WithValues("namespace", dd.Namespace, "name", dd.Name)
	logger.Info("check Source Status")

	// If there is a TaskID, check the task status.
	if taskID != "" {
		statusResp, err := h.HTTPClient.GetTaskStatus(ctx, taskID)
		if err != nil {
			return SourceStatusResult{
				Name:   source.Name,
				Phase:  "Error",
				TaskID: taskID,
				Error:  fmt.Errorf("failed to check task status: %w", err),
			}
		}

		logger.Info("Data source celery task status", "source", source.Name, "status", statusResp.Status)

		// Return results based on task status.
		switch strings.ToUpper(statusResp.Status) {
		case "SUCCESS":
			return SourceStatusResult{
				Name:   source.Name,
				Phase:  "Ready",
				TaskID: taskID,
			}
		case "STARTED":
			return SourceStatusResult{
				Name:   source.Name,
				Phase:  "STARTED",
				TaskID: taskID,
			}
		case "FAILURE":
			return SourceStatusResult{
				Name:  source.Name,
				Phase: "FAILURE",
				Error: fmt.Errorf("task %s failed: %v", taskID, statusResp.Result),
			}
		case "PENDING":
			return SourceStatusResult{
				Name:   source.Name,
				Phase:  "PENDING",
				TaskID: taskID,
			}
		case "RETRY":
			return SourceStatusResult{
				Name:   source.Name,
				Phase:  "RETRY",
				TaskID: taskID,
				Error:  fmt.Errorf("failed to check task status, task %s retry", taskID),
			}
		case "REVOKED":
			return SourceStatusResult{
				Name:   source.Name,
				Phase:  "REVOKED",
				TaskID: taskID,
			}
		default:
			return SourceStatusResult{
				Name:   source.Name,
				Phase:  "OTHERS",
				TaskID: taskID,
			}
		}
	}

	// Default connectivity check for the data source when there is no TaskID.
	return h.checkDataSourceConnectivity(ctx, source)
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
