package k8s

import (
	"fmt"

	apierrors "k8s.io/apimachinery/pkg/api/errors"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// Helper functions for type conversion

func interfaceSliceToStringSlice(slice []interface{}) []string {
	result := make([]string, 0, len(slice))
	for _, v := range slice {
		if str, ok := v.(string); ok {
			result = append(result, str)
		}
	}
	return result
}

func getStringValue(m map[string]interface{}, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getInt32Value(m map[string]interface{}, key string) int32 {
	switch v := m[key].(type) {
	case int32:
		return v
	case int:
		return int32(v)
	case float64:
		return int32(v)
	default:
		return 0
	}
}

func getInt64Value(m map[string]interface{}, key string) int64 {
	switch v := m[key].(type) {
	case int64:
		return v
	case int:
		return int64(v)
	case float64:
		return int64(v)
	default:
		return 0
	}
}

func getBoolValue(m map[string]interface{}, key string) bool {
	if v, ok := m[key].(bool); ok {
		return v
	}
	return false
}

// handleK8sError converts Kubernetes API errors to domain errors
// This is the Anti-Corruption Layer pattern - translating infrastructure concerns to domain language
func handleK8sError(err error, resourceType, name string) error {
	if apierrors.IsNotFound(err) {
		return domain.NewNotFoundError(resourceType, name)
	}
	if apierrors.IsAlreadyExists(err) {
		return domain.NewAlreadyExistsError(resourceType, name)
	}
	if apierrors.IsConflict(err) {
		return domain.NewConflictError(fmt.Sprintf("%s '%s' has been modified", resourceType, name))
	}
	if apierrors.IsForbidden(err) {
		return fmt.Errorf("%w: %v", domain.ErrForbidden, err)
	}
	if apierrors.IsUnauthorized(err) {
		return fmt.Errorf("%w: %v", domain.ErrUnauthorized, err)
	}
	if apierrors.IsInvalid(err) || apierrors.IsBadRequest(err) {
		return fmt.Errorf("%w: %v", domain.ErrInvalidInput, err)
	}
	// For other errors, return as internal error
	return domain.NewInternalError(err)
}
