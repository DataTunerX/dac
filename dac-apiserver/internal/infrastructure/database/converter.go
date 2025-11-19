package database

import (
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/ent"
)

// toUserEntity 从 ent.User 转换为 domain entity.User
// Infrastructure 层 → Domain 层of边界转换（符合依赖方向）
func toUserEntity(u *ent.User) *entity.User {
	if u == nil {
		return nil
	}
	return &entity.User{
		ID:           u.ID.String(),
		Username:     u.Username,
		PasswordHash: u.PasswordHash,
		LastLoginAt:  u.LastLoginAt,
		DeletedAt:    u.DeletedAt,
		CreatedAt:    u.CreatedAt,
		UpdatedAt:    u.UpdatedAt,
	}
}

// toRunEntity 从 ent.Run 转换为 domain entity.Run
func toRunEntity(r *ent.Run) *entity.Run {
	if r == nil {
		return nil
	}
	return &entity.Run{
		ID:        r.ID.String(),
		UserID:    r.UserID.String(),
		AgentID:   r.AgentID,
		CreatedAt: r.CreatedAt,
		UpdatedAt: r.UpdatedAt,
	}
}
