package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PlatformRolePermission holds the schema definition for the platform-role ↔ permission binding.
type PlatformRolePermission struct {
	ent.Schema
}

// Fields of the PlatformRolePermission.
func (PlatformRolePermission) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("ID"),
		field.UUID("role_id", uuid.UUID{}).
			Comment("平台角色ID"),
		field.UUID("permission_id", uuid.UUID{}).
			Comment("权限点ID"),
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("创建时间"),
	}
}

// Edges of the PlatformRolePermission.
func (PlatformRolePermission) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("role", PlatformRole.Type).
			Ref("permissions").
			Field("role_id").
			Unique().
			Required(),
	}
}

// Indexes of the PlatformRolePermission.
func (PlatformRolePermission) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("role_id", "permission_id").Unique(),
	}
}