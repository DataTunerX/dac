package main

import "fmt"

// Handler processes incoming API requests.
type Handler struct {
	processor DataProcessor
}

// NewHandler creates a new Handler.
func NewHandler(proc DataProcessor) *Handler {
	return &Handler{processor: proc}
}

// ProcessRequest handles an API request end-to-end.
func (h *Handler) ProcessRequest(payload string) (string, error) {
	fmt.Printf("Processing request: %s\n", payload)

	helper := NewHelper(h.processor)
	result, err := helper.HandleRequest(payload)
	if err != nil {
		return "", fmt.Errorf("handler error: %w", err)
	}

	return result, nil
}

// HealthCheck reports the handler health status.
func (h *Handler) HealthCheck() bool {
	return h.processor != nil
}
