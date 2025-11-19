package database

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/ent"
	"github.com/lvyanru/dac-apiserver/internal/ent/user"
)

// userRepository is UserRepository interfaceofdatabaseimplementation
type userRepository struct {
	client *ent.Client
}

// NewUserRepository create一个newof UserRepository 实例
func NewUserRepository(client *ent.Client) domain.UserRepository {
	return &userRepository{
		client: client,
	}
}

// Create createuser
func (r *userRepository) Create(ctx context.Context, username, passwordHash string) (*entity.User, error) {
	created, err := r.client.User.Create().
		SetUsername(username).
		SetPasswordHash(passwordHash).
		Save(ctx)

	if err != nil {
		// 检查is否is唯一约束错误
		if ent.IsConstraintError(err) {
			return nil, domain.NewAlreadyExistsError("User", username)
		}
		return nil, fmt.Errorf("failed to create user: %w", err)
	}

	return toUserEntity(created), nil
}

// GetByUsername based onuser名查找（只查询未删除ofuser）
func (r *userRepository) GetByUsername(ctx context.Context, username string) (*entity.User, error) {
	u, err := r.client.User.Query().
		Where(
			user.Username(username),
			user.DeletedAtIsNil(), // 只查询未删除ofuser
		).
		Only(ctx)

	if err != nil {
		if ent.IsNotFound(err) {
			return nil, domain.NewNotFoundError("User", username)
		}
		return nil, fmt.Errorf("failed to get user by username: %w", err)
	}

	return toUserEntity(u), nil
}

// GetByID based on ID 查找（只查询未删除ofuser）
func (r *userRepository) GetByID(ctx context.Context, userID string) (*entity.User, error) {
	uid, err := uuid.Parse(userID)
	if err != nil {
		return nil, fmt.Errorf("invalid user id: %w", err)
	}

	u, err := r.client.User.Query().
		Where(
			user.ID(uid),
			user.DeletedAtIsNil(), // 只查询未删除ofuser
		).
		Only(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			return nil, domain.NewNotFoundError("User", userID)
		}
		return nil, fmt.Errorf("failed to get user by id: %w", err)
	}

	return toUserEntity(u), nil
}

// List 列表查询（支持分页，只返回未删除ofuser）
func (r *userRepository) List(ctx context.Context, offset, limit int) ([]*entity.User, error) {
	users, err := r.client.User.Query().
		Where(user.DeletedAtIsNil()). // 只查询未删除ofuser
		Order(ent.Desc(user.FieldCreatedAt)).
		Offset(offset).
		Limit(limit).
		All(ctx)

	if err != nil {
		return nil, fmt.Errorf("failed to list users: %w", err)
	}

	// 转换为 domain entity
	result := make([]*entity.User, len(users))
	for i, u := range users {
		result[i] = toUserEntity(u)
	}

	return result, nil
}

// Count get总数（只统计未删除ofuser）
func (r *userRepository) Count(ctx context.Context) (int, error) {
	count, err := r.client.User.Query().
		Where(user.DeletedAtIsNil()). // 只统计未删除ofuser
		Count(ctx)

	if err != nil {
		return 0, fmt.Errorf("failed to count users: %w", err)
	}

	return count, nil
}

// Delete 软Delete user（标记为已删除，不物理删除）
func (r *userRepository) Delete(ctx context.Context, userID string) error {
	uid, err := uuid.Parse(userID)
	if err != nil {
		return fmt.Errorf("invalid user id: %w", err)
	}

	now := time.Now()
	err = r.client.User.UpdateOneID(uid).
		Where(user.DeletedAtIsNil()). // 只能删除未删除ofuser
		SetDeletedAt(now).
		Exec(ctx)

	if err != nil {
		if ent.IsNotFound(err) {
			return domain.NewNotFoundError("User", userID)
		}
		return fmt.Errorf("failed to soft delete user: %w", err)
	}

	return nil
}

// UpdateLastLogin 更new最后登录时间
func (r *userRepository) UpdateLastLogin(ctx context.Context, userID string) error {
	uid, err := uuid.Parse(userID)
	if err != nil {
		return fmt.Errorf("invalid user id: %w", err)
	}

	now := time.Now()
	err = r.client.User.UpdateOneID(uid).
		SetLastLoginAt(now).
		Exec(ctx)

	if err != nil {
		if ent.IsNotFound(err) {
			return domain.NewNotFoundError("User", userID)
		}
		return fmt.Errorf("failed to update last login: %w", err)
	}

	return nil
}
