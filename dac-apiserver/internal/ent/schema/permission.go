package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Permission holds the schema definition for a permission point.
type Permission struct {
	ent.Schema
}

// Fields of the Permission.
func (Permission) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("权限点ID"),
		field.String("code").
			NotEmpty().
			Unique().
			MaxLen(64).
			Comment("权限点编码，全局唯一，如 agent:create"),
		field.String("name").
			NotEmpty().
			MaxLen(64).
			Comment("权限点展示名"),
		field.String("resource").
			NotEmpty().
			MaxLen(64).
			Comment("资源域，如 agent / descriptor / configmap"),
		field.String("action").
			NotEmpty().
			MaxLen(32).
			Comment("动作，如 read / write / manage"),
		field.String("http_method").
			Default("*").
			Comment("允许的HTTP方法；\"*\"任意，逗号分隔多方法"),
		field.String("http_path").
			NotEmpty().
			MaxLen(256).
			Comment("路径模板，支持 * 匹配一段、** 匹配后缀"),
		field.String("description").
			Optional().
			Comment("权限点描述"),
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

// Indexes of the Permission.
func (Permission) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("resource", "action"),
	}
}