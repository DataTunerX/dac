package usecase

import (
	"context"
	"fmt"
	"log/slog"
	"regexp"

	"golang.org/x/crypto/bcrypt"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// userUsecase is UserUsecase interfaceofimplementation
type userUsecase struct {
	userRepo domain.UserRepository
	logger   *slog.Logger
}

// NewUserUsecase create一个newof UserUsecase 实例
func NewUserUsecase(
	userRepo domain.UserRepository,
	logger *slog.Logger,
) domain.UserUsecase {
	return &userUsecase{
		userRepo: userRepo,
		logger:   logger,
	}
}

// Register User registration
func (u *userUsecase) Register(ctx context.Context, username, password string) (*entity.User, error) {
	// 验证请求
	if err := u.validateRegisterRequest(username, password); err != nil {
		return nil, err
	}

	// 检查user名is否已exists
	existingUser, err := u.userRepo.GetByUsername(ctx, username)
	if err == nil && existingUser != nil {
		return nil, domain.NewAlreadyExistsError("User", username)
	}
	if err != nil && !domain.IsNotFound(err) {
		return nil, fmt.Errorf("failed to check username: %w", err)
	}

	// 哈希密码
	passwordHash, err := hashPassword(password)
	if err != nil {
		return nil, fmt.Errorf("failed to hash password: %w", err)
	}

	// createuser
	user, err := u.userRepo.Create(ctx, username, passwordHash)
	if err != nil {
		return nil, fmt.Errorf("failed to create user: %w", err)
	}

	u.logger.Info("user registered successfully", "user_id", user.ID, "username", user.Username)
	return user, nil
}

// Login User login验证
func (u *userUsecase) Login(ctx context.Context, username, password string) (*entity.User, error) {
	// 查找user
	user, err := u.userRepo.GetByUsername(ctx, username)
	if err != nil {
		if domain.IsNotFound(err) {
			return nil, domain.NewInvalidInputError("invalid username or password")
		}
		return nil, fmt.Errorf("failed to get user: %w", err)
	}

	// 验证密码
	if err := verifyPassword(user.PasswordHash, password); err != nil {
		return nil, domain.NewInvalidInputError("invalid username or password")
	}

	// 更new最后登录时间（异步，不影响登录流程）
	go func() {
		if err := u.userRepo.UpdateLastLogin(context.Background(), user.ID); err != nil {
			u.logger.Error("failed to update last login", "error", err, "user_id", user.ID)
		}
	}()

	u.logger.Info("user logged in successfully", "user_id", user.ID, "username", user.Username)
	return user, nil
}

// GetUser getUser information
func (u *userUsecase) GetUser(ctx context.Context, userID string) (*entity.User, error) {
	user, err := u.userRepo.GetByID(ctx, userID)
	if err != nil {
		return nil, err
	}
	return user, nil
}

// ListUsers User list（分页）
func (u *userUsecase) ListUsers(ctx context.Context, page, pageSize int) ([]*entity.User, int, error) {
	// 参数验证
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20 // 默认每页20条
	}

	offset := (page - 1) * pageSize

	// 查询User list
	users, err := u.userRepo.List(ctx, offset, pageSize)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to list users: %w", err)
	}

	// get总数
	total, err := u.userRepo.Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to count users: %w", err)
	}

	return users, total, nil
}

// DeleteUser Delete user
func (u *userUsecase) DeleteUser(ctx context.Context, userID string) error {
	// 检查useris否exists
	_, err := u.userRepo.GetByID(ctx, userID)
	if err != nil {
		return err
	}

	// Delete user
	if err := u.userRepo.Delete(ctx, userID); err != nil {
		return fmt.Errorf("failed to delete user: %w", err)
	}

	u.logger.Info("user deleted successfully", "user_id", userID)
	return nil
}

// ============ 辅助函数 ============

// validateRegisterRequest 验证注册请求
func (u *userUsecase) validateRegisterRequest(username, password string) error {
	// user名验证：3-50字符，只能包含字母、数字、下划线
	usernameRegex := regexp.MustCompile(`^[a-zA-Z0-9_]{3,50}$`)
	if !usernameRegex.MatchString(username) {
		return domain.NewInvalidInputError("username must be 3-50 characters and contain only letters, numbers, and underscores")
	}

	// 密码验证：至少6个字符
	if len(password) < 6 {
		return domain.NewInvalidInputError("password must be at least 6 characters")
	}
	if len(password) > 72 {
		return domain.NewInvalidInputError("password too long (max 72 characters)")
	}

	return nil
}

// hashPassword 使用 bcrypt 哈希密码
func hashPassword(password string) (string, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

// verifyPassword 验证密码
func verifyPassword(hash, password string) error {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
}
