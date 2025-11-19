package dto

import (
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// RegisterRequest User registration请求（HTTP）
type RegisterRequest struct {
	Username string `json:"username" binding:"required,min=3,max=50"`
	Password string `json:"password" binding:"required,min=6,max=72"` // bcrypt 限制72字节
}

// LoginRequest User login请求（HTTP）
type LoginRequest struct {
	Username string `json:"username" binding:"required"`
	Password string `json:"password" binding:"required"`
}

// LoginResponse 登录响应（HTTP）
type LoginResponse struct {
	Token  string        `json:"token"`
	Expire string        `json:"expire"`
	User   *UserResponse `json:"user"`
}

// UserResponse User information响应（HTTP）
type UserResponse struct {
	ID          string  `json:"id"`
	Username    string  `json:"username"`
	LastLoginAt *string `json:"last_login_at,omitempty"`
	CreatedAt   string  `json:"created_at"`
}

// UserListResponse User list响应（HTTP）
type UserListResponse struct {
	Users      []*UserResponse `json:"users"`
	Total      int             `json:"total"`
	Page       int             `json:"page"`
	PageSize   int             `json:"page_size"`
	TotalPages int             `json:"total_pages"`
}

// ToUserResponse converts entity.User to UserResponse DTO
func ToUserResponse(user *entity.User) *UserResponse {
	resp := &UserResponse{
		ID:        user.ID,
		Username:  user.Username,
		CreatedAt: user.CreatedAt.Format(time.RFC3339),
	}

	if user.LastLoginAt != nil {
		lastLogin := user.LastLoginAt.Format(time.RFC3339)
		resp.LastLoginAt = &lastLogin
	}

	return resp
}

// ToUserListResponse converts a slice of entity.User to UserListResponse DTO
func ToUserListResponse(users []*entity.User, total, page, pageSize int) *UserListResponse {
	userResponses := make([]*UserResponse, len(users))
	for i, user := range users {
		userResponses[i] = ToUserResponse(user)
	}

	totalPages := (total + pageSize - 1) / pageSize
	if totalPages < 1 {
		totalPages = 1
	}

	return &UserListResponse{
		Users:      userResponses,
		Total:      total,
		Page:       page,
		PageSize:   pageSize,
		TotalPages: totalPages,
	}
}
