package logger

import (
	"context"
	"fmt"
	"io"
	"log/slog"

	"github.com/cloudwego/hertz/pkg/common/hlog"
)

// HertzSlogAdapter adapts slog to Hertz's hlog interface
type HertzSlogAdapter struct {
	logger *slog.Logger
}

// NewHertzSlogAdapter creates a new Hertz logger adapter using slog
func NewHertzSlogAdapter(logger *slog.Logger) *HertzSlogAdapter {
	return &HertzSlogAdapter{
		logger: logger,
	}
}

// Trace logs a trace message
func (h *HertzSlogAdapter) Trace(v ...interface{}) {
	h.logger.Debug(formatMessage(v...))
}

// Debug logs a debug message
func (h *HertzSlogAdapter) Debug(v ...interface{}) {
	h.logger.Debug(formatMessage(v...))
}

// Info logs an info message
func (h *HertzSlogAdapter) Info(v ...interface{}) {
	h.logger.Info(formatMessage(v...))
}

// Notice logs a notice message (mapped to Info in slog)
func (h *HertzSlogAdapter) Notice(v ...interface{}) {
	h.logger.Info(formatMessage(v...))
}

// Warn logs a warning message
func (h *HertzSlogAdapter) Warn(v ...interface{}) {
	h.logger.Warn(formatMessage(v...))
}

// Error logs an error message
func (h *HertzSlogAdapter) Error(v ...interface{}) {
	h.logger.Error(formatMessage(v...))
}

// Fatal logs a fatal message
func (h *HertzSlogAdapter) Fatal(v ...interface{}) {
	h.logger.Error(formatMessage(v...))
}

// Tracef logs a formatted trace message
func (h *HertzSlogAdapter) Tracef(format string, v ...interface{}) {
	h.logger.Debug(formatMessagef(format, v...))
}

// Debugf logs a formatted debug message
func (h *HertzSlogAdapter) Debugf(format string, v ...interface{}) {
	h.logger.Debug(formatMessagef(format, v...))
}

// Infof logs a formatted info message
func (h *HertzSlogAdapter) Infof(format string, v ...interface{}) {
	h.logger.Info(formatMessagef(format, v...))
}

// Noticef logs a formatted notice message
func (h *HertzSlogAdapter) Noticef(format string, v ...interface{}) {
	h.logger.Info(formatMessagef(format, v...))
}

// Warnf logs a formatted warning message
func (h *HertzSlogAdapter) Warnf(format string, v ...interface{}) {
	h.logger.Warn(formatMessagef(format, v...))
}

// Errorf logs a formatted error message
func (h *HertzSlogAdapter) Errorf(format string, v ...interface{}) {
	h.logger.Error(formatMessagef(format, v...))
}

// Fatalf logs a formatted fatal message
func (h *HertzSlogAdapter) Fatalf(format string, v ...interface{}) {
	h.logger.Error(formatMessagef(format, v...))
}

// CtxTracef logs a formatted trace message with context
func (h *HertzSlogAdapter) CtxTracef(ctx context.Context, format string, v ...interface{}) {
	h.logger.DebugContext(ctx, formatMessagef(format, v...))
}

// CtxDebugf logs a formatted debug message with context
func (h *HertzSlogAdapter) CtxDebugf(ctx context.Context, format string, v ...interface{}) {
	h.logger.DebugContext(ctx, formatMessagef(format, v...))
}

// CtxInfof logs a formatted info message with context
func (h *HertzSlogAdapter) CtxInfof(ctx context.Context, format string, v ...interface{}) {
	h.logger.InfoContext(ctx, formatMessagef(format, v...))
}

// CtxNoticef logs a formatted notice message with context
func (h *HertzSlogAdapter) CtxNoticef(ctx context.Context, format string, v ...interface{}) {
	h.logger.InfoContext(ctx, formatMessagef(format, v...))
}

// CtxWarnf logs a formatted warning message with context
func (h *HertzSlogAdapter) CtxWarnf(ctx context.Context, format string, v ...interface{}) {
	h.logger.WarnContext(ctx, formatMessagef(format, v...))
}

// CtxErrorf logs a formatted error message with context
func (h *HertzSlogAdapter) CtxErrorf(ctx context.Context, format string, v ...interface{}) {
	h.logger.ErrorContext(ctx, formatMessagef(format, v...))
}

// CtxFatalf logs a formatted fatal message with context
func (h *HertzSlogAdapter) CtxFatalf(ctx context.Context, format string, v ...interface{}) {
	h.logger.ErrorContext(ctx, formatMessagef(format, v...))
}

// SetLevel sets the log level (no-op for compatibility)
func (h *HertzSlogAdapter) SetLevel(level hlog.Level) {
	// slog level is set during initialization, this is for interface compatibility
}

// SetOutput sets the output writer (no-op for compatibility)
func (h *HertzSlogAdapter) SetOutput(writer io.Writer) {
	// slog output is set during initialization, this is for interface compatibility
}

// Helper functions
func formatMessage(v ...interface{}) string {
	if len(v) == 0 {
		return ""
	}
	if len(v) == 1 {
		if s, ok := v[0].(string); ok {
			return s
		}
	}
	return fmt.Sprint(v...)
}

func formatMessagef(format string, v ...interface{}) string {
	return fmt.Sprintf(format, v...)
}
