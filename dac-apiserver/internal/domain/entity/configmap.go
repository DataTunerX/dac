package entity

import "time"

// ConfigMap represents a Kubernetes ConfigMap managed by DAC UI.
type ConfigMap struct {
	Name      string
	Namespace string
	Labels    map[string]string
	Data      map[string]string
	CreatedAt time.Time
}

