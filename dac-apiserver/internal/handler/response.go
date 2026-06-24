// Package handler provides HTTP handlers for the DAC API (Hertz).
// Handlers bind request data, call usecases, and return unified JSON responses
// via SuccessResponse, CreatedResponse, ErrorResponse.
package handler

import (
	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/protocol/consts"
	"errors"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// Response is the unified JSON response envelope for all API responses.
type Response struct {
	Code    string      `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// SuccessResponse returns a successful response
func SuccessResponse(c *app.RequestContext, data interface{}) {
	c.JSON(consts.StatusOK, Response{
		Code:    "SUCCESS",
		Message: "operation successful",
		Data:    data,
	})
}

// CreatedResponse returns a created response
func CreatedResponse(c *app.RequestContext, data interface{}) {
	c.JSON(consts.StatusCreated, Response{
		Code:    "CREATED",
		Message: "resource created successfully",
		Data:    data,
	})
}

// NoContentResponse returns a no content response (typically for delete operations)
func NoContentResponse(c *app.RequestContext) {
	c.Status(consts.StatusNoContent)
}

// AcceptedResponse returns an accepted async response (202).
func AcceptedResponse(c *app.RequestContext, data interface{}) {
	c.JSON(consts.StatusAccepted, Response{
		Code:    "ACCEPTED",
		Message: "operation accepted",
		Data:    data,
	})
}

// ErrorResponse returns an error response based on error type
func ErrorResponse(c *app.RequestContext, err error) {
	// getuser友好of错误消息（不暴露内部细节）
	getUserMessage := func(err error) string {
		if domainErr, ok := err.(*domain.DomainError); ok {
			return domainErr.UserMessage()
		}
		// 对于非 DomainError，返回通用消息
		return "an error occurred"
	}

	// Return different status codes based on error type
	switch {
	case domain.IsNotFound(err):
		c.JSON(consts.StatusNotFound, Response{
			Code:    "NOT_FOUND",
			Message: getUserMessage(err),
		})
	case domain.IsAlreadyExists(err):
		c.JSON(consts.StatusConflict, Response{
			Code:    "ALREADY_EXISTS",
			Message: getUserMessage(err),
		})
	case domain.IsInvalidInput(err):
		c.JSON(consts.StatusBadRequest, Response{
			Code:    "INVALID_INPUT",
			Message: getUserMessage(err),
		})
	case domain.IsConflict(err):
		c.JSON(consts.StatusConflict, Response{
			Code:    "CONFLICT",
			Message: getUserMessage(err),
		})
	case errors.Is(err, domain.ErrUnauthorized):
		c.JSON(consts.StatusUnauthorized, Response{
			Code:    "UNAUTHORIZED",
			Message: getUserMessage(err),
		})
	default:
		// Internal error：不暴露任何细节
		c.JSON(consts.StatusInternalServerError, Response{
			Code:    "INTERNAL_ERROR",
			Message: "internal server error",
		})
	}
}

// BadRequestResponse returns a bad request response
func BadRequestResponse(c *app.RequestContext, message string) {
	c.JSON(consts.StatusBadRequest, Response{
		Code:    "BAD_REQUEST",
		Message: message,
	})
}

// ListResponse 列表响应结构
type ListResponse struct {
	Items      interface{} `json:"items"`
	TotalCount int         `json:"totalCount"`
}
