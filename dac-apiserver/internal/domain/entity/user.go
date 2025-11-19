package entity

import "time"

// User userentity（Domain 层，不依赖 JSON 序列化）
type User struct {
	ID           string
	Username     string
	PasswordHash string     // 密码哈希
	LastLoginAt  *time.Time // 最后登录时间
	DeletedAt    *time.Time // 软删除时间
	CreatedAt    time.Time
	UpdatedAt    time.Time
}

// IsDeleted 检查useris否已被删除
func (u *User) IsDeleted() bool {
	return u.DeletedAt != nil
}
