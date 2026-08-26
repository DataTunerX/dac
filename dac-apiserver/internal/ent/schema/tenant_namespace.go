package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TenantNamespace holds the schema definition for a tenant's bound K8s namespace.
type TenantNamespace struct {
	ent.Schema
}

// Fields of the TenantNamespace.
func (TenantNamespace) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("ID"),
		field.UUID("tenant_id", uuid.UUID{}).
			Comment("所属租户ID"),
		field.String("namespace").
			NotEmpty().
			MaxLen(253).
			Comment("K8s namespace 名"),
		field.Time("created_at").
			Default(time.Now).
			Immutable().
			Comment("创建时间"),
	}
}

// Edges of the TenantNamespace.
func (TenantNamespace) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("tenant", Tenant.Type).
			Ref("namespaces").
			Field("tenant_id").
			Unique().
			Required(),
	}
}

// Indexes of the TenantNamespace.
func (TenantNamespace) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "namespace").Unique(),
	}
}