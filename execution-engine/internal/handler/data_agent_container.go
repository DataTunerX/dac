package handler

import (
	"context"

	"fmt"
	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
	"github.com/DataTunerX/dac/execution-engine/client/k8s"
	"github.com/DataTunerX/dac/execution-engine/internal/generator"
	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"time"
)

// DataAgentContainerHandler handles the reconciliation logic for DataAgentContainer resources.
type DataAgentContainerHandler struct {
	K8sServices  k8s.Services
	EventsCli    k8s.Event
	Kubeclient   client.Client
	Logger       logr.Logger
	DACGenerator *generator.DataAgentContainerGenerator
}

// AgentStatusResult contains the result of checking agent status
type AgentStatusResult struct {
	Endpoint              dacv1alpha1.Endpoint
	ActiveDataDescriptors []dacv1alpha1.ActiveDataDescriptor
	Phase                 string
	Error                 error
}

func (h *DataAgentContainerHandler) Do(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) error {
	logger := h.Logger.WithValues("namespace", dac.Namespace, "name", dac.Name)
	logger.Info("Processing DataAgentContainer")

	// handle dac logic
	err := h.handleDAC(ctx, dac)
	if err != nil {
		return err
	}

	// handle dac status
	err = h.handleDACStatus(ctx, dac)
	if err != nil {
		return err
	}

	return nil
}

func (h *DataAgentContainerHandler) handleDAC(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) error {
	logger := h.Logger.WithValues("namespace", dac.Namespace, "name", dac.Name)
	logger.Info("Processing DataAgentContainer Logic")

	// if service or deployment not exist, will create them. if service or deployment exist, do nothing.
	err := h.DACGenerator.Do(ctx, dac)
	if err != nil {
		return err
	}

	return nil
}

// Do processes the DataAgentContainer resource and updates its status.
func (h *DataAgentContainerHandler) handleDACStatus(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) error {
	logger := h.Logger.WithValues("namespace", dac.Namespace, "name", dac.Name)
	logger.Info("Processing DataAgentContainer Status")

	// Save the original status for comparison later
	originalStatus := dac.Status.DeepCopy()

	// Initialize Status if needed
	newStatus := dacv1alpha1.DataAgentContainerStatus{
		Conditions:            make([]dacv1alpha1.Condition, 0),
		ActiveDataDescriptors: make([]dacv1alpha1.ActiveDataDescriptor, 0),
		Endpoint:              dac.Status.Endpoint,
	}

	// Copy existing conditions if they exist
	if dac.Status.Conditions != nil {
		newStatus.Conditions = append(newStatus.Conditions, dac.Status.Conditions...)
	}

	// Copy active data descriptors if they exist
	if dac.Status.ActiveDataDescriptors != nil {
		newStatus.ActiveDataDescriptors = append(newStatus.ActiveDataDescriptors, dac.Status.ActiveDataDescriptors...)
	}

	// Set creating condition if this is a new resource
	if dac.Status.Endpoint.Address == "" {
		newStatus.SetCreateCondition("Initializing DataAgentContainer")
	}

	// Check agent status
	status := h.checkDACStatus(ctx, dac)

	// Update status based on check results
	if status.Error != nil {
		// Handle error state
		logger.Error(status.Error, "Agent status check failed")
		h.EventsCli.Warning(dac, "AgentCheckFailed", fmt.Sprintf("Agent check failed: %v", status.Error))

		c := dacv1alpha1.NewCondition(
			dacv1alpha1.ConditionFailed,
			corev1.ConditionTrue,
			"CheckFailed",
			fmt.Sprintf("Agent status check failed: %v", status.Error),
		)
		newStatus.SetDataAgentContainerCondition(*c)
	} else {
		// Update successful status
		newStatus.Endpoint = status.Endpoint
		newStatus.ActiveDataDescriptors = status.ActiveDataDescriptors

		c := dacv1alpha1.NewCondition(
			dacv1alpha1.ConditionAvailable,
			corev1.ConditionTrue,
			"Healthy",
			"Agent is healthy and ready",
		)
		newStatus.SetDataAgentContainerCondition(*c)
		h.EventsCli.Normal(dac, "AgentHealthy", "Agent is healthy")
	}

	// Sort conditions by time
	newStatus.DescConditionsByTime()

	// Compare the new status with original, ignoring time fields if needed
	if !h.isStatusEqualIgnoringTime(*originalStatus, newStatus) {
		// Update the status in the original object
		dac.Status = newStatus

		// Update the status in Kubernetes
		if err := h.Kubeclient.Status().Update(ctx, dac); err != nil {
			logger.Error(err, "Failed to update DataAgentContainer status")
			return fmt.Errorf("failed to update status: %w", err)
		}
		logger.Info("Status updated successfully")
	} else {
		logger.Info("Status unchanged, skipping update")
	}

	if status.Error != nil {
		return status.Error
	}

	return nil
}

func (h *DataAgentContainerHandler) checkK8SServiceExist(dac *dacv1alpha1.DataAgentContainer) bool {
	serviceName := h.DACGenerator.GenerateDataAgentContainerServiceName(dac)
	if _, err := h.K8sServices.GetService(dac.Namespace, serviceName); err != nil {
		if errors.IsNotFound(err) {
			return false
		}
		return false
	}
	return true
}

func (h *DataAgentContainerHandler) checkK8SDeploymentExist(dac *dacv1alpha1.DataAgentContainer) bool {
	deploymentName := h.DACGenerator.GenerateDataAgentContainerDeploymentName(dac)
	_, err := h.K8sServices.GetDeployment(dac.Namespace, deploymentName)
	if err != nil {
		// If no resource we need to create.
		if errors.IsNotFound(err) {
			return false
		}
		return false
	}
	return true
}

func (h *DataAgentContainerHandler) generateActiveDataDescriptors(dac *dacv1alpha1.DataAgentContainer) []dacv1alpha1.ActiveDataDescriptor {
	if dac == nil || len(dac.Spec.DataPolicy.SourceNameSelector) == 0 {
		return nil
	}

	var activeDescriptors []dacv1alpha1.ActiveDataDescriptor
	currentTime := time.Now().Format(time.RFC3339)

	for _, sourceName := range dac.Spec.DataPolicy.SourceNameSelector {
		descriptor := dacv1alpha1.ActiveDataDescriptor{
			Name:       sourceName,
			Namespace:  dac.Namespace,
			LastSynced: currentTime,
		}
		activeDescriptors = append(activeDescriptors, descriptor)
	}

	return activeDescriptors
}

// checkAgentStatus checks the current status of the agent.
func (h *DataAgentContainerHandler) checkDACStatus(ctx context.Context, dac *dacv1alpha1.DataAgentContainer) AgentStatusResult {
	serviceName := h.DACGenerator.GenerateDataAgentContainerServiceName(dac)
	deploymentName := h.DACGenerator.GenerateDataAgentContainerDeploymentName(dac)

	phase := "Ready"
	endpoint := fmt.Sprintf("%s.%s.svc.cluster.local", serviceName, dac.Namespace)
	activeDataDescriptor := h.generateActiveDataDescriptors(dac)

	serviceExist := h.checkK8SServiceExist(dac)
	if !serviceExist {
		phase := "FAILED"
		return AgentStatusResult{
			Endpoint: dacv1alpha1.Endpoint{
				Address:  endpoint,
				Port:     10100,
				Protocol: "sse",
			},
			ActiveDataDescriptors: activeDataDescriptor,
			Phase:                 phase,
			Error:                 fmt.Errorf("service %s not create success.", serviceName),
		}
	}

	deploymentExist := h.checkK8SDeploymentExist(dac)
	if !deploymentExist {
		phase := "FAILED"
		return AgentStatusResult{
			Endpoint: dacv1alpha1.Endpoint{
				Address:  endpoint,
				Port:     10100,
				Protocol: "sse",
			},
			ActiveDataDescriptors: activeDataDescriptor,
			Phase:                 phase,
			Error:                 fmt.Errorf("deployment %s not create success.", deploymentName),
		}
	}

	// If both the service and deployment have been created, start checking if the service is healthy (you can use the A2A client to send a simple request). If it's not healthy, set the Phase to Starting.
	// https://github.com/a2aproject/a2a-go/
	if false {
		phase = "Starting"
		return AgentStatusResult{
			Endpoint: dacv1alpha1.Endpoint{
				Address:  endpoint,
				Port:     10100,
				Protocol: "sse",
			},
			ActiveDataDescriptors: activeDataDescriptor,
			Phase:                 phase,
		}
	} else {
		// If the service is functioning normally, set the Phase to Ready.
		return AgentStatusResult{
			Endpoint: dacv1alpha1.Endpoint{
				Address:  endpoint,
				Port:     10100,
				Protocol: "sse",
			},
			ActiveDataDescriptors: activeDataDescriptor,
			Phase:                 phase,
		}
	}

}

// isStatusEqualIgnoringTime compares two DataAgentContainerStatus objects while ignoring time fields
func (h *DataAgentContainerHandler) isStatusEqualIgnoringTime(oldStatus, newStatus dacv1alpha1.DataAgentContainerStatus) bool {
	// Compare Endpoint
	if oldStatus.Endpoint.Address != newStatus.Endpoint.Address ||
		oldStatus.Endpoint.Port != newStatus.Endpoint.Port ||
		oldStatus.Endpoint.Protocol != newStatus.Endpoint.Protocol {
		return false
	}

	// Compare ActiveDataDescriptors (ignoring LastSynced)
	if len(oldStatus.ActiveDataDescriptors) != len(newStatus.ActiveDataDescriptors) {
		return false
	}
	for i := range oldStatus.ActiveDataDescriptors {
		oldDesc := oldStatus.ActiveDataDescriptors[i]
		newDesc := newStatus.ActiveDataDescriptors[i]
		if oldDesc.Name != newDesc.Name ||
			oldDesc.Namespace != newDesc.Namespace {
			return false
		}
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

	return true
}
