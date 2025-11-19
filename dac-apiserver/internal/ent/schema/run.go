package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Run holds the schema definition for the Run entity.
type Run struct {
	ent.Schema
}

// Fields of the Run.
func (Run) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("运行ID"),
		field.UUID("user_id", uuid.UUID{}).
			Comment("用户ID"),
		field.String("agent_id").
			Optional().
			Comment("使用的Agent ID"),
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

// Edges of the Run.
func (Run) Edges() []ent.Edge {
	return []ent.Edge{
		// Run belongs to User
		edge.From("user", User.Type).
			Ref("runs").
			Field("user_id").
			Unique().
			Required(),
	}
}

// Indexes of the Run.
func (Run) Indexes() []ent.Index {
	return []ent.Index{
		// Index on user_id for faster queries
		index.Fields("user_id"),
	}
}
