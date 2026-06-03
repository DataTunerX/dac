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
	Secret string `mapstructure:"secret"`
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

	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
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
