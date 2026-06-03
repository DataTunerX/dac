package main

import "fmt"

// DataProcessor defines the contract for processing data.
type DataProcessor interface {
	Process(data string) (string, error)
	Validate(data string) bool
}

// DefaultProcessor is the primary implementation of DataProcessor.
type DefaultProcessor struct {
	Config ProcessorConfig
}

// ProcessorConfig holds configuration for processors.
type ProcessorConfig struct {
	Timeout int
	Retries int
}

// NewDefaultProcessor creates a new DefaultProcessor with default config.
func NewDefaultProcessor() *DefaultProcessor {
	return &DefaultProcessor{
		Config: ProcessorConfig{
			Timeout: 30,
			Retries: 3,
		},
	}
}

// Process implements DataProcessor.Process.
func (p *DefaultProcessor) Process(data string) (string, error) {
	if !p.Validate(data) {
		return "", fmt.Errorf("invalid data: %s", data)
	}
	result := TransformData(data)
	return result, nil
}

// Validate checks if the provided data is valid.
func (p *DefaultProcessor) Validate(data string) bool {
	return len(data) > 0 && len(data) < 1024
}

// TransformData applies transformation rules to the raw data.
func TransformData(data string) string {
	return fmt.Sprintf("processed: %s", data)
}

// Helper bridges the processor with external systems.
type Helper struct {
	processor DataProcessor
}

// NewHelper creates a helper bound to a processor.
func NewHelper(proc DataProcessor) *Helper {
	return &Helper{processor: proc}
}

// HandleRequest processes a request through the pipeline.
func (h *Helper) HandleRequest(input string) (string, error) {
	validated := h.processor.Validate(input)
	if !validated {
		return "", fmt.Errorf("validation failed")
	}
	result, err := h.processor.Process(input)
	if err != nil {
		return "", fmt.Errorf("process error: %w", err)
	}
	return FinalizeOutput(result), nil
}

// FinalizeOutput applies post-processing to the result.
func FinalizeOutput(data string) string {
	return fmt.Sprintf("[final] %s [ok]", data)
}

func main() {

	proc := NewDefaultProcessor()
	_ = proc
}
