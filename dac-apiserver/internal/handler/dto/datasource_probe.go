package dto

// ProbeDataSourceRequest is the wire-format input for POST /datasources/probe.
//
// Field tags are explicit: Hertz/encoding/json's case-insensitive
// matching is convenient but fragile, and probing endpoints are easy
// targets for misconfigured clients. Lock the contract down.
type ProbeDataSourceRequest struct {
	Type     string `json:"type" validate:"required"`
	Host     string `json:"host" validate:"required"`
	Port     int    `json:"port" validate:"required,gt=0,lte=65535"`
	User     string `json:"user"`
	Password string `json:"password"`
}

// ProbeDataSourceResponse is the wire-format output. We expose only
// what the UI needs; in particular, we never echo back the password.
type ProbeDataSourceResponse struct {
	Databases []string `json:"databases"`
	Version   string   `json:"version,omitempty"`
	LatencyMs int64    `json:"latencyMs"`
}

// SupportedProbeTypesResponse is returned by GET /datasources/probe/types.
type SupportedProbeTypesResponse struct {
	Types []string `json:"types"`
}
