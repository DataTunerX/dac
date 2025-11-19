package usecase

import (
	"context"
	"log/slog"
	"os"
	"testing"
	"time"

	"golang.org/x/crypto/bcrypt"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
)

// Mock UserRepository for testing (使用简单ofimplementation，避免重复定义)
type testUserRepository struct {
	users map[string]*entity.User
}

func newTestUserRepository() *testUserRepository {
	return &testUserRepository{
		users: make(map[string]*entity.User),
	}
}

func (r *testUserRepository) Create(ctx context.Context, username, passwordHash string) (*entity.User, error) {
	user := &entity.User{
		ID:           "test-user-id",
		Username:     username,
		PasswordHash: passwordHash,
		CreatedAt:    time.Now(),
		UpdatedAt:    time.Now(),
	}
	r.users[username] = user
	return user, nil
}

func (r *testUserRepository) GetByUsername(ctx context.Context, username string) (*entity.User, error) {
	if user, ok := r.users[username]; ok {
		return user, nil
	}
	return nil, domain.NewNotFoundError("User", username)
}

func (r *testUserRepository) GetByID(ctx context.Context, userID string) (*entity.User, error) {
	return &entity.User{ID: userID, Username: "testuser"}, nil
}

func (r *testUserRepository) List(ctx context.Context, offset, limit int) ([]*entity.User, error) {
	return []*entity.User{}, nil
}

func (r *testUserRepository) Count(ctx context.Context) (int, error) {
	return 0, nil
}

func (r *testUserRepository) Delete(ctx context.Context, userID string) error {
	return nil
}

func (r *testUserRepository) UpdateLastLogin(ctx context.Context, userID string) error {
	return nil
}

func TestRegister(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))

	tests := []struct {
		name        string
		username    string
		password    string
		setupMock   func(*testUserRepository)
		wantErr     bool
		errContains string
	}{
		{
			name:     "成功注册",
			username: "testuser",
			password: "password123",
			setupMock: func(m *testUserRepository) {
				// user名不exists - 默认就不exists
			},
			wantErr: false,
		},
		{
			name:     "user名已exists",
			username: "existinguser",
			password: "password123",
			setupMock: func(m *testUserRepository) {
				// 预先create一个已existsofuser
				m.users["existinguser"] = &entity.User{ID: "existing-id", Username: "existinguser"}
			},
			wantErr:     true,
			errContains: "already exists",
		},
		{
			name:        "user名太短",
			username:    "ab",
			password:    "password123",
			wantErr:     true,
			errContains: "3-50 characters",
		},
		{
			name:        "user名包含非法字符",
			username:    "user@name",
			password:    "password123",
			wantErr:     true,
			errContains: "letters, numbers, and underscores",
		},
		{
			name:        "密码太短",
			username:    "testuser",
			password:    "12345",
			wantErr:     true,
			errContains: "at least 6 characters",
		},
		{
			name:        "密码太长",
			username:    "testuser",
			password:    "a" + string(make([]byte, 73)), // 超过 72 字符
			wantErr:     true,
			errContains: "too long",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockRepo := newTestUserRepository()
			if tt.setupMock != nil {
				tt.setupMock(mockRepo)
			}

			uc := NewUserUsecase(mockRepo, logger)
			user, err := uc.Register(context.Background(), tt.username, tt.password)

			if tt.wantErr {
				if err == nil {
					t.Errorf("期望错误，但成功了")
				} else if tt.errContains != "" && !contains(err.Error(), tt.errContains) {
					t.Errorf("错误信息 = %v, 期望包含 %v", err, tt.errContains)
				}
			} else {
				if err != nil {
					t.Errorf("不期望错误，但failure了: %v", err)
				}
				if user == nil {
					t.Errorf("期望返回user，但为 nil")
				}
			}
		})
	}
}

func TestLogin(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(os.Stdout, nil))

	// create一个测试密码哈希
	testPasswordHash, _ := bcrypt.GenerateFromPassword([]byte("correctpassword"), bcrypt.DefaultCost)

	tests := []struct {
		name        string
		username    string
		password    string
		setupMock   func(*testUserRepository)
		wantErr     bool
		errContains string
	}{
		{
			name:     "成功登录",
			username: "testuser",
			password: "correctpassword",
			setupMock: func(m *testUserRepository) {
				m.users["testuser"] = &entity.User{
					ID:           "test-id",
					Username:     "testuser",
					PasswordHash: string(testPasswordHash),
				}
			},
			wantErr: false,
		},
		{
			name:     "User not found",
			username: "nonexistent",
			password: "password123",
			setupMock: func(m *testUserRepository) {
				// User not found - 默认就不exists
			},
			wantErr:     true,
			errContains: "invalid username or password", // 不泄露userexists性
		},
		{
			name:     "密码错误",
			username: "testuser",
			password: "wrongpassword",
			setupMock: func(m *testUserRepository) {
				m.users["testuser"] = &entity.User{
					ID:           "test-id",
					Username:     "testuser",
					PasswordHash: string(testPasswordHash),
				}
			},
			wantErr:     true,
			errContains: "invalid username or password", // 统一错误信息
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockRepo := newTestUserRepository()
			if tt.setupMock != nil {
				tt.setupMock(mockRepo)
			}

			uc := NewUserUsecase(mockRepo, logger)
			user, err := uc.Login(context.Background(), tt.username, tt.password)

			if tt.wantErr {
				if err == nil {
					t.Errorf("期望错误，但成功了")
				} else if tt.errContains != "" && !contains(err.Error(), tt.errContains) {
					t.Errorf("错误信息 = %v, 期望包含 %v", err, tt.errContains)
				}
			} else {
				if err != nil {
					t.Errorf("不期望错误，但failure了: %v", err)
				}
				if user == nil {
					t.Errorf("期望返回user，但为 nil")
				}
			}
		})
	}
}

func TestPasswordSecurity(t *testing.T) {
	t.Run("密码哈希不可逆", func(t *testing.T) {
		password := "securePassword123"
		hash, err := hashPassword(password)
		if err != nil {
			t.Fatalf("哈希密码failure: %v", err)
		}

		// 验证哈希值不等于原密码
		if hash == password {
			t.Error("密码哈希不应该等于原密码")
		}

		// 验证哈希值足够长（bcrypt 输出固定长度）
		if len(hash) < 50 {
			t.Error("bcrypt 哈希长度异常")
		}
	})

	t.Run("相同密码产生不同哈希", func(t *testing.T) {
		password := "testPassword"
		hash1, _ := hashPassword(password)
		hash2, _ := hashPassword(password)

		// bcrypt 每次生成不同of salt，所以哈希应该不同
		if hash1 == hash2 {
			t.Error("相同密码应该产生不同of哈希（salt 不同）")
		}
	})

	t.Run("密码验证正确性", func(t *testing.T) {
		password := "correctPassword"
		hash, _ := hashPassword(password)

		// 正确密码应该验证通过
		if err := verifyPassword(hash, password); err != nil {
			t.Error("正确密码验证failure")
		}

		// 错误密码应该验证failure
		if err := verifyPassword(hash, "wrongPassword"); err == nil {
			t.Error("错误密码不应该验证通过")
		}
	})
}

// 辅助函数
func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && (s[:len(substr)] == substr || contains(s[1:], substr)))
}
