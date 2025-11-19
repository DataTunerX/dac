package domain

import (
	"errors"
	"fmt"
)

// 预定义of领域错误
var (
	// ErrNotFound 资源不exists
	ErrNotFound = errors.New("resource not found")
	// ErrAlreadyExists 资源已exists
	ErrAlreadyExists = errors.New("resource already exists")
	// ErrInvalidInput 无效of输入
	ErrInvalidInput = errors.New("invalid input")
	// ErrConflict 资源冲突（版本不匹配）
	ErrConflict = errors.New("resource conflict")
	// ErrUnauthorized Unauthorized
	ErrUnauthorized = errors.New("unauthorized")
	// ErrForbidden 禁止访问
	ErrForbidden = errors.New("forbidden")
	// ErrInternal Internal error
	ErrInternal = errors.New("internal error")
)

// DomainError 领域错误
type DomainError struct {
	Code    string
	Message string
	Err     error
}

// Error implementation error interface（用于日志andInternal error传递）
func (e *DomainError) Error() string {
	if e.Err != nil {
		return fmt.Sprintf("%s: %s (%v)", e.Code, e.Message, e.Err)
	}
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

// UserMessage 返回user友好of错误消息（不包含Internal error细节）
func (e *DomainError) UserMessage() string {
	return e.Message
}

// Unwrap 返回包装of错误
func (e *DomainError) Unwrap() error {
	return e.Err
}

// NewNotFoundError create资源不exists错误
func NewNotFoundError(resourceType, name string) error {
	return &DomainError{
		Code:    "NOT_FOUND",
		Message: fmt.Sprintf("%s '%s' not found", resourceType, name),
		Err:     ErrNotFound,
	}
}

// NewAlreadyExistsError create资源已exists错误
func NewAlreadyExistsError(resourceType, name string) error {
	return &DomainError{
		Code:    "ALREADY_EXISTS",
		Message: fmt.Sprintf("%s '%s' already exists", resourceType, name),
		Err:     ErrAlreadyExists,
	}
}

// NewInvalidInputError create无效输入错误
func NewInvalidInputError(message string) error {
	return &DomainError{
		Code:    "INVALID_INPUT",
		Message: message,
		Err:     ErrInvalidInput,
	}
}

// NewConflictError create资源冲突错误
func NewConflictError(message string) error {
	return &DomainError{
		Code:    "CONFLICT",
		Message: message,
		Err:     ErrConflict,
	}
}

// NewInternalError createInternal error
func NewInternalError(err error) error {
	return &DomainError{
		Code:    "INTERNAL_ERROR",
		Message: "an internal error occurred", // 不暴露Internal error细节
		Err:     fmt.Errorf("%w: %v", ErrInternal, err),
	}
}

// IsNotFound 判断is否为资源不exists错误
func IsNotFound(err error) bool {
	return errors.Is(err, ErrNotFound)
}

// IsAlreadyExists 判断is否为资源已exists错误
func IsAlreadyExists(err error) bool {
	return errors.Is(err, ErrAlreadyExists)
}

// IsInvalidInput 判断is否为无效输入错误
func IsInvalidInput(err error) bool {
	return errors.Is(err, ErrInvalidInput)
}

// IsConflict 判断is否为资源冲突错误
func IsConflict(err error) bool {
	return errors.Is(err, ErrConflict)
}

// IsInternalError 判断is否为Internal error
func IsInternalError(err error) bool {
	return errors.Is(err, ErrInternal)
}
