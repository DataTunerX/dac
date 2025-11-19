package handler

import (
	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/protocol/consts"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// Response 统一响应结构
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
