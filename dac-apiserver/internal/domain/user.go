package domain

import (
	"context"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// ============ Repository interface ============

// UserRepository user数据访问interface
type UserRepository interface {
	// Create createuser
	Create(ctx context.Context, username, passwordHash string) (*entity.User, error)

	// GetByUsername based onuser名查找（用于登录）
	GetByUsername(ctx context.Context, username string) (*entity.User, error)

	// GetByID based on ID 查找
	GetByID(ctx context.Context, userID string) (*entity.User, error)

	// List 列表查询（支持分页）
	List(ctx context.Context, offset, limit int) ([]*entity.User, error)

	// Count get总数
	Count(ctx context.Context) (int, error)

	// Delete Delete user
	Delete(ctx context.Context, userID string) error

	// UpdateLastLogin 更new最后登录时间
	UpdateLastLogin(ctx context.Context, userID string) error
}

// ============ Usecase interface ============

// UserUsecase user业务逻辑interface
type UserUsecase interface {
	// Register User registration
	Register(ctx context.Context, username, password string) (*entity.User, error)

	// Login User login验证（返回User information）
	Login(ctx context.Context, username, password string) (*entity.User, error)

	// GetUser getUser information
	GetUser(ctx context.Context, userID string) (*entity.User, error)

	// ListUsers User list（分页）
	ListUsers(ctx context.Context, page, pageSize int) ([]*entity.User, int, error)

	// DeleteUser Delete user
	DeleteUser(ctx context.Context, userID string) error
}
