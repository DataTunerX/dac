package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// DiscoveryJob holds the schema definition for the DiscoveryJob entity.
// It persists infra scan jobs for the frontend list/detail pages.
type DiscoveryJob struct {
	ent.Schema
}

// DiscoveryService is a small JSON-storable struct for discovered services.
// Keep it independent from domain types to avoid package coupling in ent schema.
type DiscoveryService struct {
	Host        string            `json:"host"`
	Port        int               `json:"port"`
	Protocol    string            `json:"protocol"`
	ServiceType string            `json:"serviceType"`
	Product     string            `json:"product,omitempty"`
	Version     string            `json:"version,omitempty"`
	TLS         bool              `json:"tls"`
	Metadata    map[string]string `json:"metadata,omitempty"`
}

func (DiscoveryJob) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable().
			Comment("扫描任务ID"),
		field.String("name").
			Optional().
			Comment("用户自定义名称"),
		field.String("target").
			NotEmpty().
			Comment("扫描目标（IP/Host）"),
		field.String("ports_spec").
			Optional().
			Comment("端口范围输入（原始字符串）"),
		field.String("status").
			Default("PENDING").
			Comment("任务状态"),
		field.String("error").
			Optional().
			Comment("失败原因"),
		field.Time("started_at").
			Optional().
			Nillable().
			Comment("开始时间"),
		field.Time("finished_at").
			Optional().
			Nillable().
			Comment("结束时间"),
		field.JSON("services", []DiscoveryService{}).
			Optional().
			Comment("扫描结果（服务列表）"),
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

func (DiscoveryJob) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("target"),
		index.Fields("status"),
		index.Fields("created_at"),
	}
}

