package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Tenant holds the schema definition for a tenant.
type Tenant struct {
	ent.Schema
}

// Fields of the Tenant.
func (Tenant) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("租户ID"),
		field.String("code").
			NotEmpty().
			Unique().
			MaxLen(64).
			Comment("租户编码，全局唯一"),
		field.String("name").
			NotEmpty().
			MaxLen(128).
			Comment("租户展示名"),
		field.String("status").
			Default("active").
			Comment("状态：active / disabled"),
		field.String("description").
			Optional().
			Comment("租户描述"),
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

// Edges of the Tenant.
func (Tenant) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("namespaces", TenantNamespace.Type),
		edge.To("roles", TenantRole.Type),
		edge.To("members", TenantUser.Type),
	}
}

// Indexes of the Tenant.
func (Tenant) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("status"),
	}
}