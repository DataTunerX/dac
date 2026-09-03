package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PlatformUserRole holds the schema definition for a user's platform role binding.
type PlatformUserRole struct {
	ent.Schema
}

// Fields of the PlatformUserRole.
func (PlatformUserRole) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("ID"),
		field.UUID("user_id", uuid.UUID{}).
			Comment("用户ID（users 表）"),
		field.UUID("role_id", uuid.UUID{}).
			Comment("平台角色ID"),
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("创建时间"),
	}
}

// Edges of the PlatformUserRole.
func (PlatformUserRole) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("role", PlatformRole.Type).
			Ref("users").
			Field("role_id").
			Unique().
			Required(),
	}
}

// Indexes of the PlatformUserRole.
func (PlatformUserRole) Indexes() []ent.Index {
	return []ent.Index{
		// 一个用户对一个平台角色只绑定一次
		index.Fields("user_id", "role_id").Unique(),
		index.Fields("user_id"),
		index.Fields("role_id"),
	}
}