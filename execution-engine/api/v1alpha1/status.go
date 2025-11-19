package v1alpha1

import (
	"sort"
	"time"

	corev1 "k8s.io/api/core/v1"
)

// ConditionType defines the condition that the RF can have
type ConditionType string

const (
	DataDescriptionConditionAdd ConditionType = "Added"
	ConditionAvailable          ConditionType = "Available"
	ConditionHealthy            ConditionType = "Healthy"
	ConditionRunning            ConditionType = "Running"
	ConditionCreating           ConditionType = "Creating"
	ConditionRecovering         ConditionType = "Recovering"
	ConditionUpdating           ConditionType = "Updating"
	ConditionFailed             ConditionType = "Failed"
	ConditionNotReady           ConditionType = "NotReady"
)

// Condition saves the state information of the cr
type Condition struct {
	// Status of cr condition.
	Type ConditionType `json:"type"`
	// Status of the condition, one of True, False, Unknown.
	Status corev1.ConditionStatus `json:"status"`
	// The last time this condition was updated.
	LastUpdateTime string `json:"lastUpdateTime,omitempty"`
	// The reason for the condition's last transition.
	Reason string `json:"reason,omitempty"`
	// A human readable message indicating details about the transition.
	Message string `json:"message,omitempty"`
}

func NewCondition(condType ConditionType, status corev1.ConditionStatus, reason, message string) *Condition {
	now := time.Now()
	nowString := now.Format(time.RFC3339)
	return &Condition{
		Type:           condType,
		Status:         status,
		LastUpdateTime: nowString,
		Reason:         reason,
		Message:        message,
	}
}

// DataDescriptor Status
func (dds *DataDescriptorStatus) DescConditionsByTime() {
	sort.Slice(dds.Conditions, func(i, j int) bool {
		t1, _ := time.Parse(time.RFC3339, dds.Conditions[i].LastUpdateTime)
		t2, _ := time.Parse(time.RFC3339, dds.Conditions[j].LastUpdateTime)
		return t1.After(t2)
	})
}

func getDataDescriptorCondition(status *DataDescriptorStatus, t ConditionType) (int, *Condition) {
	for i, c := range status.Conditions {
		if t == c.Type {
			return i, &c
		}
	}
	return -1, nil
}

func (dds *DataDescriptorStatus) SetDataDescriptorCondition(c Condition) {
	pos, cp := getDataDescriptorCondition(dds, c.Type)
	if cp != nil && cp.Status == c.Status && cp.Reason == c.Reason && cp.Message == c.Message {
		now := time.Now()
		nowString := now.Format(time.RFC3339)
		dds.Conditions[pos].LastUpdateTime = nowString
		return
	}

	if cp != nil {
		dds.Conditions[pos] = c
	} else {
		dds.Conditions = append(dds.Conditions, c)
	}
}

func (dds *DataDescriptorStatus) SetCreateCondition(message string) {
	c := NewCondition(ConditionCreating, corev1.ConditionTrue, "Creating", message)
	dds.SetDataDescriptorCondition(*c)
}

// DataAgentContainer Status
func (dacs *DataAgentContainerStatus) DescConditionsByTime() {
	sort.Slice(dacs.Conditions, func(i, j int) bool {
		t1, _ := time.Parse(time.RFC3339, dacs.Conditions[i].LastUpdateTime)
		t2, _ := time.Parse(time.RFC3339, dacs.Conditions[j].LastUpdateTime)
		return t1.After(t2)
	})
}

func getDataAgentContainerCondition(status *DataAgentContainerStatus, t ConditionType) (int, *Condition) {
	for i, c := range status.Conditions {
		if t == c.Type {
			return i, &c
		}
	}
	return -1, nil
}

func (dacs *DataAgentContainerStatus) SetDataAgentContainerCondition(c Condition) {
	pos, cp := getDataAgentContainerCondition(dacs, c.Type)
	if cp != nil && cp.Status == c.Status && cp.Reason == c.Reason && cp.Message == c.Message {
		now := time.Now()
		nowString := now.Format(time.RFC3339)
		dacs.Conditions[pos].LastUpdateTime = nowString
		return
	}

	if cp != nil {
		dacs.Conditions[pos] = c
	} else {
		dacs.Conditions = append(dacs.Conditions, c)
	}
}

func (dacs *DataAgentContainerStatus) SetCreateCondition(message string) {
	c := NewCondition(ConditionCreating, corev1.ConditionTrue, "Creating", message)
	dacs.SetDataAgentContainerCondition(*c)
}
