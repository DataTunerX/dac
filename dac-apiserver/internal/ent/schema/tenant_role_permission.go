package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TenantRolePermission holds the schema definition for the tenant-role ↔ permission binding.
type TenantRolePermission struct {
	ent.Schema
}

// Fields of the TenantRolePermission.
func (TenantRolePermission) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("ID"),
		field.UUID("role_id", uuid.UUID{}).
			Comment("租户角色ID"),
		field.UUID("permission_id", uuid.UUID{}).
			Comment("权限点ID"),
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("创建时间"),
	}
}

// Edges of the TenantRolePermission.
func (TenantRolePermission) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("role", TenantRole.Type).
			Ref("permissions").
			Field("role_id").
			Unique().
			Required(),
	}
}

// Indexes of the TenantRolePermission.
func (TenantRolePermission) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("role_id", "permission_id").Unique(),
	}
}