package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TenantUser holds the schema definition for a user's tenant membership and role.
type TenantUser struct {
	ent.Schema
}

// Fields of the TenantUser.
func (TenantUser) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("ID"),
		field.UUID("tenant_id", uuid.UUID{}).
			Comment("所属租户ID"),
		field.UUID("user_id", uuid.UUID{}).
			Comment("用户ID（users 表）"),
		field.UUID("role_id", uuid.UUID{}).
			Comment("该用户在此租户绑定的租户角色ID"),
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("创建时间"),
	}
}

// Edges of the TenantUser.
func (TenantUser) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("tenant", Tenant.Type).
			Ref("members").
			Field("tenant_id").
			Unique().
			Required(),
		edge.From("role", TenantRole.Type).
			Ref("users").
			Field("role_id").
			Unique().
			Required(),
	}
}

// Indexes of the TenantUser.
func (TenantUser) Indexes() []ent.Index {
	return []ent.Index{
		// 一个用户在一个租户只能有一个角色
		index.Fields("tenant_id", "user_id").Unique(),
		// 一个用户只能属于一个租户
		index.Fields("user_id").Unique(),
		index.Fields("role_id"),
	}
}