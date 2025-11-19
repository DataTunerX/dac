package logger

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"strings"

	"github.com/lvyanru/dac-apiserver/internal/config"
)

// Setup initializes the logging system
func Setup(cfg config.LogConfig) error {
	// Parse log level
	level, err := parseLevel(cfg.Level)
	if err != nil {
		return fmt.Errorf("invalid log level: %w", err)
	}

	// Setup log output
	var writer io.Writer
	switch cfg.Output {
	case "stdout":
		writer = os.Stdout
	case "stderr":
		writer = os.Stderr
	case "file":
		if cfg.FilePath == "" {
			return fmt.Errorf("log file path is required when output is 'file'")
		}
		file, err := os.OpenFile(cfg.FilePath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
		if err != nil {
			return fmt.Errorf("failed to open log file: %w", err)
		}
		writer = file
	default:
		return fmt.Errorf("invalid log output: %s", cfg.Output)
	}

	// Setup handler options
	opts := &slog.HandlerOptions{
		Level:     level,
		AddSource: cfg.AddSource,
		// Replace default attributes to customize output
		ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
			// Customize time format to RFC3339 with timezone
			if a.Key == slog.TimeKey {
				return slog.Attr{
					Key:   "time",
					Value: slog.StringValue(a.Value.Time().Format("2006-01-02T15:04:05.000Z07:00")),
				}
			}
			return a
		},
	}

	// Choose handler based on format
	var handler slog.Handler
	switch cfg.Format {
	case "json":
		handler = slog.NewJSONHandler(writer, opts)
	case "text":
		handler = slog.NewTextHandler(writer, opts)
	default:
		return fmt.Errorf("invalid log format: %s", cfg.Format)
	}

	// Set as default logger
	logger := slog.New(handler)
	slog.SetDefault(logger)

	slog.Info("logger initialized successfully",
		"level", cfg.Level,
		"format", cfg.Format,
		"output", cfg.Output,
		"timezone", "local (using system timezone)",
	)

	return nil
}

// parseLevel parses log level string to slog.Level
func parseLevel(level string) (slog.Level, error) {
	switch strings.ToLower(level) {
	case "debug":
		return slog.LevelDebug, nil
	case "info":
		return slog.LevelInfo, nil
	case "warn", "warning":
		return slog.LevelWarn, nil
	case "error":
		return slog.LevelError, nil
	default:
		return slog.LevelInfo, fmt.Errorf("unknown log level: %s", level)
	}
}

// FromContext retrieves logger from context
// Returns default logger if none found in context
func FromContext(ctx context.Context) *slog.Logger {
	if logger, ok := ctx.Value(loggerKey).(*slog.Logger); ok {
		return logger
	}
	return slog.Default()
}

// WithContext adds logger to context
func WithContext(ctx context.Context, logger *slog.Logger) context.Context {
	return context.WithValue(ctx, loggerKey, logger)
}

// WithRequestID adds request ID to logger
func WithRequestID(logger *slog.Logger, requestID string) *slog.Logger {
	return logger.With("request_id", requestID)
}

// WithError adds error information to logger
func WithError(logger *slog.Logger, err error) *slog.Logger {
	if err == nil {
		return logger
	}
	return logger.With("error", err.Error())
}

// WithFields adds multiple fields to logger
func WithFields(logger *slog.Logger, fields map[string]interface{}) *slog.Logger {
	args := make([]interface{}, 0, len(fields)*2)
	for k, v := range fields {
		args = append(args, k, v)
	}
	return logger.With(args...)
}

type contextKey string

const loggerKey contextKey = "logger"
