package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PlatformRole holds the schema definition for a platform-level (global) role.
type PlatformRole struct {
	ent.Schema
}

// Fields of the PlatformRole.
func (PlatformRole) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("角色ID"),
		field.String("code").
			NotEmpty().
			Unique().
			MaxLen(64).
			Comment("平台角色编码，如 super_admin / ops / auditor"),
		field.String("name").
			NotEmpty().
			MaxLen(64).
			Comment("角色展示名"),
		field.Bool("is_super").
			Default(false).
			Comment("是否超管；命中即全通，免权限点校验"),
		field.String("description").
			Optional().
			Comment("角色描述"),
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

// Edges of the PlatformRole.
func (PlatformRole) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("permissions", PlatformRolePermission.Type),
		edge.To("users", PlatformUserRole.Type),
	}
}

// Indexes of the PlatformRole.
func (PlatformRole) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("is_super"),
	}
}