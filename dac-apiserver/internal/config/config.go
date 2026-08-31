package config

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/viper"
)

// Config holds all configuration for the application
type Config struct {
	Server       ServerConfig       `mapstructure:"server"`
	Log          LogConfig          `mapstructure:"log"`
	Observability ObservabilityConfig `mapstructure:"observability"`
	JWT          JWTConfig          `mapstructure:"jwt"`
	RoutingAgent    RoutingAgentConfig    `mapstructure:"routing_agent"`
	DataServices    DataServicesConfig    `mapstructure:"data_services"`
	SemanticGrouper SemanticGrouperConfig `mapstructure:"semantic_grouper"`
	AgentRegistry   AgentRegistryConfig   `mapstructure:"agent_registry"`
	SkillHub        SkillHubConfig        `mapstructure:"skill_hub"`
	TDBPipeline     TDBPipelineConfig     `mapstructure:"tdb_pipeline"`
	Database      DatabaseConfig      `mapstructure:"database"`
}

// ServerConfig holds server configuration
type ServerConfig struct {
	Host               string `mapstructure:"host"`
	Port               int    `mapstructure:"port"`
	Mode               string `mapstructure:"mode"`
	ReadTimeout        time.Duration
	WriteTimeout       time.Duration
	MaxRequestBodySize int `mapstructure:"max_request_body_size"` // in MB
}

// LogConfig holds logging configuration
type LogConfig struct {
	Level     string `mapstructure:"level"`
	Format    string `mapstructure:"format"`
	Output    string `mapstructure:"output"`
	FilePath  string `mapstructure:"file_path"`
	AddSource bool   `mapstructure:"add_source"`
}

// ObservabilityConfig holds observability configuration
type ObservabilityConfig struct {
	EnableMetrics   bool   `mapstructure:"enable_metrics"`
	MetricsPort     int    `mapstructure:"metrics_port"`
	EnableTracing   bool   `mapstructure:"enable_tracing"`
	TracingEndpoint string `mapstructure:"tracing_endpoint"`
}

// JWTConfig holds JWT configuration
type JWTConfig struct {
	Secret       string        `mapstructure:"secret"`
	Timeout      time.Duration `mapstructure:"timeout"`
	MaxRefresh   time.Duration `mapstructure:"max_refresh"`
	CookieSecure bool          `mapstructure:"cookie_secure"`
	CookieDomain string        `mapstructure:"cookie_domain"`
}

// RoutingAgentConfig holds Routing Agent configuration
type RoutingAgentConfig struct {
	BaseURL        string        `mapstructure:"base_url"`
	Timeout        time.Duration `mapstructure:"timeout"`
	SessionTimeout time.Duration `mapstructure:"session_timeout"`
}

// DataServicesConfig holds Data Services configuration
type DataServicesConfig struct {
	BaseURL string        `mapstructure:"base_url"`
	Timeout time.Duration `mapstructure:"timeout"`
}

// SemanticGrouperConfig holds semantic-grouper service configuration.
type SemanticGrouperConfig struct {
	BaseURL string        `mapstructure:"base_url"`
	Timeout time.Duration `mapstructure:"timeout"`
}

// AgentRegistryConfig holds agent-registry service endpoints.
type AgentRegistryConfig struct {
	OrchestratorBaseURL    string        `mapstructure:"orchestrator_base_url"`
	BizOrchestratorBaseURL string        `mapstructure:"biz_orchestrator_base_url"`
	Timeout                time.Duration `mapstructure:"timeout"`
}

// SkillHubConfig holds skill-hub registry endpoint.
type SkillHubConfig struct {
	BaseURL string        `mapstructure:"base_url"`
	Timeout time.Duration `mapstructure:"timeout"`
}

// TDBPipelineConfig holds the TDB pipeline controller endpoint, the DAC caller
// credentials it allowlists, and DAC's copy of its target allowlist. The
// controller exposes no endpoint for the allowlist, so the targets below must
// be kept in step with the controller's domain-config ConfigMap.
type TDBPipelineConfig struct {
	BaseURL     string                    `mapstructure:"base_url"`
	CallerID    string                    `mapstructure:"caller_id"`
	Token       string                    `mapstructure:"token"`
	Timeout     time.Duration             `mapstructure:"timeout"`
	Images      []string                  `mapstructure:"images"`
	LLMProfiles []string                  `mapstructure:"llm_profiles"`
	Defaults    TDBPipelineDefaultsConfig `mapstructure:"defaults"`
	Targets     []TDBPipelineTargetConfig `mapstructure:"targets"`
	Skill       TDBPipelineSkillConfig    `mapstructure:"skill"`
}

// TDBPipelineSkillConfig controls automatic publication of a TDB QA skill for a
// target once a run has ingested content into it.
type TDBPipelineSkillConfig struct {
	// AutoPublish turns the behaviour on. Default true.
	AutoPublish *bool `mapstructure:"auto_publish"`
	// Namespace is the skill-hub namespace generated skills are published into.
	Namespace string `mapstructure:"namespace"`
	// Agent controls the skill agent created to load the generated skill.
	Agent TDBPipelineAgentConfig `mapstructure:"agent"`
}

// TDBPipelineAgentConfig describes the DataAgentContainer created to load a
// generated skill. Publishing a skill only makes it available; an agent has to
// list it before anything can query the ingested corpus.
type TDBPipelineAgentConfig struct {
	// AutoCreate turns agent creation on. Default true.
	AutoCreate *bool `mapstructure:"auto_create"`
	// Namespace is where the DataAgentContainer is created.
	Namespace                 string `mapstructure:"namespace"`
	ExpertLLM                 string `mapstructure:"expert_llm"`
	PlannerLLM                string `mapstructure:"planner_llm"`
	ExpertAgentMaxSteps       string `mapstructure:"expert_agent_max_steps"`
	OrchestratorAgentMaxLoops string `mapstructure:"orchestrator_agent_max_loops"`
}

// AgentAutoCreateEnabled reports whether a finished run creates a skill agent.
func (c TDBPipelineConfig) AgentAutoCreateEnabled() bool {
	if c.Skill.Agent.AutoCreate == nil {
		return true
	}
	return *c.Skill.Agent.AutoCreate
}

// SkillAutoPublishEnabled reports whether finished runs publish a skill.
func (c TDBPipelineConfig) SkillAutoPublishEnabled() bool {
	if c.Skill.AutoPublish == nil {
		return true
	}
	return *c.Skill.AutoPublish
}

// TDBPipelineTargetConfig is one selectable TDB target.
type TDBPipelineTargetConfig struct {
	ID            string `mapstructure:"id"`
	Domain        string `mapstructure:"domain"`
	Label         string `mapstructure:"label"`
	GatewayURL    string `mapstructure:"gateway_url"`
	DomainProfile string `mapstructure:"domain_profile"`
	Collection    string `mapstructure:"collection"`
	SkillAgent    string `mapstructure:"skill_agent"`
	Test          bool   `mapstructure:"test"`
}

// TDBPipelineDefaultsConfig pre-fills the create-run form.
type TDBPipelineDefaultsConfig struct {
	Collection          string `mapstructure:"collection"`
	Image               string `mapstructure:"image"`
	LLMProfile          string `mapstructure:"llm_profile"`
	RunsPrefix          string `mapstructure:"runs_prefix"`
	StatusPrefix        string `mapstructure:"status_prefix"`
	AttemptStatusPrefix string `mapstructure:"attempt_status_prefix"`
}

// DatabaseConfig holds database configuration
type DatabaseConfig struct {
	Driver          string        `mapstructure:"driver"`
	Host            string        `mapstructure:"host"`
	Port            int           `mapstructure:"port"`
	User            string        `mapstructure:"user"`
	Password        string        `mapstructure:"password"`
	Database        string        `mapstructure:"database"`
	MaxOpenConns    int           `mapstructure:"max_open_conns"`
	MaxIdleConns    int           `mapstructure:"max_idle_conns"`
	ConnMaxLifetime time.Duration `mapstructure:"conn_max_lifetime"`
}

// Load loads configuration from file
func Load(cfgFile string) (*Config, error) {
	v := viper.New()

	if cfgFile != "" {
		v.SetConfigFile(cfgFile)
	} else {
		v.AddConfigPath("configs")
		v.SetConfigName("config")
		v.SetConfigType("yaml")
	}

	v.SetEnvPrefix("DAC")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	v.SetDefault("skill_hub.timeout", "120s")
	v.SetDefault("tdb_pipeline.timeout", "60s")

	// AutomaticEnv does not reach nested keys reliably through Unmarshal, and
	// the controller token must come from a Secret rather than the config file.
	if err := v.BindEnv("tdb_pipeline.token", "DAC_TDB_PIPELINE_TOKEN"); err != nil {
		return nil, fmt.Errorf("failed to bind tdb pipeline token env: %w", err)
	}
	if err := v.BindEnv("tdb_pipeline.base_url", "DAC_TDB_PIPELINE_BASE_URL"); err != nil {
		return nil, fmt.Errorf("failed to bind tdb pipeline base url env: %w", err)
	}
	if err := v.BindEnv("tdb_pipeline.caller_id", "DAC_TDB_PIPELINE_CALLER_ID"); err != nil {
		return nil, fmt.Errorf("failed to bind tdb pipeline caller id env: %w", err)
	}

	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	if cfg.JWT.Timeout == 0 {
		cfg.JWT.Timeout = 15 * time.Minute
	}
	if cfg.JWT.MaxRefresh == 0 {
		cfg.JWT.MaxRefresh = 168 * time.Hour
	}
	if cfg.SkillHub.Timeout == 0 {
		cfg.SkillHub.Timeout = 120 * time.Second
	}
	if cfg.TDBPipeline.Timeout == 0 {
		cfg.TDBPipeline.Timeout = 60 * time.Second
	}
	if len(cfg.TDBPipeline.LLMProfiles) == 0 {
		cfg.TDBPipeline.LLMProfiles = []string{"local", "openai"}
	}

	return &cfg, nil
}

// GetServerAddr returns the server address
func (c *Config) GetServerAddr() string {
	return fmt.Sprintf("%s:%d", c.Server.Host, c.Server.Port)
}

// GetReadTimeout returns the read timeout
func (c *Config) GetReadTimeout() time.Duration {
	if c.Server.ReadTimeout == 0 {
		return 10 * time.Second
	}
	return c.Server.ReadTimeout
}

// GetWriteTimeout returns the write timeout
func (c *Config) GetWriteTimeout() time.Duration {
	if c.Server.WriteTimeout == 0 {
		return 10 * time.Second
	}
	return c.Server.WriteTimeout
}
