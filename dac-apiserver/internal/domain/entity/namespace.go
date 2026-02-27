package entity

import "time"

// Namespace represents a Kubernetes namespace (for UI dropdown).
type Namespace struct {
	Name      string
	Labels    map[string]string
	CreatedAt time.Time
}

