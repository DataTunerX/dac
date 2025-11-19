package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// User holds the schema definition for the User entity.
type User struct {
	ent.Schema
}

// Fields of the User.
func (User) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("用户ID"),
		field.String("username").
			NotEmpty().
			Unique().
			MaxLen(50).
			Comment("用户名"),
		field.String("password_hash").
			NotEmpty().
			Sensitive(). // 不会在查询中自动返回
			Comment("密码哈希"),
		field.Time("last_login_at").
			Optional().
			Nillable().
			Comment("最后登录时间"),
		field.Time("deleted_at").
			Optional().
			Nillable().
			Comment("软删除时间（NULL 表示未删除）"),
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("创建时间"),
		field.Time("updated_at").
			Default(time.Now).
			UpdateDefault(time.Now).
			Comment("更新时间"),
	}
}

// Edges of the User.
func (User) Edges() []ent.Edge {
	return []ent.Edge{
		// User has many Runs
		edge.To("runs", Run.Type),
	}
}

// Indexes of the User.
func (User) Indexes() []ent.Index {
	return []ent.Index{
		// 用户名索引（包含已Delete user，确保唯一性）
		index.Fields("username"),
		// 软删除索引（快速过滤未Delete user）
		index.Fields("deleted_at"),
	}
}
