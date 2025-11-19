package k8s

import (
	"fmt"
	"github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/tools/record"

	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
)

type Event interface {
	Normal(object runtime.Object, reason, message string)
	Warning(object runtime.Object, reason, message string)

	SourceHealthy(object runtime.Object, sourceName, message string)
	SourceUnhealthy(object runtime.Object, sourceName, message string)
	SourceSyncSuccess(object runtime.Object, sourceName string, records int64)
	SourceSyncFailed(object runtime.Object, sourceName, message string)

	Created(object runtime.Object, message string)
	Updated(object runtime.Object, message string)
	Deleted(object runtime.Object, message string)

	ConditionChanged(object runtime.Object, conditionType dacv1alpha1.ConditionType, message string)
}

type EventRecorder struct {
	recorder record.EventRecorder
	logger   logr.Logger
}

func NewEvent(recorder record.EventRecorder, logger logr.Logger) Event {
	return &EventRecorder{
		recorder: recorder,
		logger:   logger.WithName("event-recorder"),
	}
}

func (e *EventRecorder) Normal(object runtime.Object, reason, message string) {
	e.recorder.Event(object, corev1.EventTypeNormal, reason, message)
	e.logger.Info(message, "reason", reason, "object", object)
}

func (e *EventRecorder) Warning(object runtime.Object, reason, message string) {
	e.recorder.Event(object, corev1.EventTypeWarning, reason, message)
	e.logger.Info(message, "reason", reason, "object", object)
}

func (e *EventRecorder) SourceHealthy(object runtime.Object, sourceName, message string) {
	reason := "SourceHealthy"
	e.recorder.Eventf(object, corev1.EventTypeNormal, reason, "datasource %s: %s", sourceName, message)
	e.logger.Info(message, "reason", reason, "source", sourceName, "object", object)
}

func (e *EventRecorder) SourceUnhealthy(object runtime.Object, sourceName, message string) {
	reason := "SourceUnhealthy"
	e.recorder.Eventf(object, corev1.EventTypeWarning, reason, "datasource %s: %s", sourceName, message)
	e.logger.Info(message, "reason", reason, "source", sourceName, "object", object)
}

func (e *EventRecorder) SourceSyncSuccess(object runtime.Object, sourceName string, records int64) {
	reason := "SourceSyncSuccess"
	message := fmt.Sprintf("datasource %s sync success，record count: %d", sourceName, records)
	e.recorder.Eventf(object, corev1.EventTypeNormal, reason, message)
	e.logger.Info(message, "reason", reason, "source", sourceName, "records", records)
}

func (e *EventRecorder) SourceSyncFailed(object runtime.Object, sourceName, message string) {
	reason := "SourceSyncFailed"
	e.recorder.Eventf(object, corev1.EventTypeWarning, reason, "datasource %s sync fail: %s", sourceName, message)
	e.logger.Info(message, "reason", reason, "source", sourceName)
}

func (e *EventRecorder) Created(object runtime.Object, message string) {
	reason := "Created"
	e.recorder.Event(object, corev1.EventTypeNormal, reason, message)
	e.logger.Info(message, "reason", reason)
}

func (e *EventRecorder) Updated(object runtime.Object, message string) {
	reason := "Updated"
	e.recorder.Event(object, corev1.EventTypeNormal, reason, message)
	e.logger.Info(message, "reason", reason)
}

func (e *EventRecorder) Deleted(object runtime.Object, message string) {
	reason := "Deleted"
	e.recorder.Event(object, corev1.EventTypeNormal, reason, message)
	e.logger.Info(message, "reason", reason)
}

func (e *EventRecorder) ConditionChanged(object runtime.Object, conditionType dacv1alpha1.ConditionType, message string) {
	reason := string(conditionType) + "ConditionChanged"
	e.recorder.Eventf(object, corev1.EventTypeNormal, reason, "condition %s change: %s", conditionType, message)
	e.logger.Info(message, "reason", reason, "condition", conditionType)
}
