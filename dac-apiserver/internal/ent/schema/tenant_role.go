package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TenantRole holds the schema definition for a tenant-local role.
type TenantRole struct {
	ent.Schema
}

// Fields of the TenantRole.
func (TenantRole) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("角色ID"),
		field.UUID("tenant_id", uuid.UUID{}).
			Comment("所属租户ID"),
		field.String("code").
			NotEmpty().
			MaxLen(64).
			Comment("角色编码，(tenant_id, code) 唯一"),
		field.String("name").
			NotEmpty().
			MaxLen(64).
			Comment("角色展示名"),
		field.Bool("is_default").
			Default(false).
			Comment("新成员未指定角色时的默认角色"),
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

// Edges of the TenantRole.
func (TenantRole) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("tenant", Tenant.Type).
			Ref("roles").
			Field("tenant_id").
			Unique().
			Required(),
		edge.To("permissions", TenantRolePermission.Type),
		edge.To("users", TenantUser.Type),
	}
}

// Indexes of the TenantRole.
func (TenantRole) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "code").Unique(),
	}
}