package config

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/viper"
)

// Config 应用配置
type Config struct {
	Server        ServerConfig        `mapstructure:"server"`
	Log           LogConfig           `mapstructure:"log"`
	Observability ObservabilityConfig `mapstructure:"observability"`
	JWT           JWTConfig           `mapstructure:"jwt"`
	RoutingAgent  RoutingAgentConfig  `mapstructure:"routing_agent"`
	Database      DatabaseConfig      `mapstructure:"database"`
}

// ServerConfig 服务器配置
type ServerConfig struct {
	Host               string        `mapstructure:"host"`
	Port               int           `mapstructure:"port"`
	Mode               string        `mapstructure:"mode"`
	ReadTimeout        time.Duration `mapstructure:"read_timeout"`
	WriteTimeout       time.Duration `mapstructure:"write_timeout"`
	MaxRequestBodySize int           `mapstructure:"max_request_body_size"`
}

// LogConfig 日志配置
type LogConfig struct {
	Level     string `mapstructure:"level"`
	Format    string `mapstructure:"format"`
	Output    string `mapstructure:"output"`
	FilePath  string `mapstructure:"file_path"`
	AddSource bool   `mapstructure:"add_source"`
}

// ObservabilityConfig 可观测性配置
type ObservabilityConfig struct {
	EnableMetrics   bool   `mapstructure:"enable_metrics"`
	MetricsPort     int    `mapstructure:"metrics_port"`
	EnableTracing   bool   `mapstructure:"enable_tracing"`
	TracingEndpoint string `mapstructure:"tracing_endpoint"`
}

// JWTConfig JWT 配置
type JWTConfig struct {
	Secret string `mapstructure:"secret"` // JWT 密钥
}

// RoutingAgentConfig Routing Agent configuration
type RoutingAgentConfig struct {
	BaseURL        string        `mapstructure:"base_url"`
	Timeout        time.Duration `mapstructure:"timeout"`         // 请求超时
	SessionTimeout time.Duration `mapstructure:"session_timeout"` // Session 超时
}

// DatabaseConfig database配置
type DatabaseConfig struct {
	Driver          string        `mapstructure:"driver"` // mysql, postgres, sqlite
	Host            string        `mapstructure:"host"`
	Port            int           `mapstructure:"port"`
	User            string        `mapstructure:"user"`
	Password        string        `mapstructure:"password"`
	Database        string        `mapstructure:"database"`
	MaxOpenConns    int           `mapstructure:"max_open_conns"`    // 最大打开连接数
	MaxIdleConns    int           `mapstructure:"max_idle_conns"`    // 最大空闲连接数
	ConnMaxLifetime time.Duration `mapstructure:"conn_max_lifetime"` // 连接最大生命周期
}

// Load 加载配置文件
func Load(configPath string) (*Config, error) {
	v := viper.New()

	// 设置配置文件路径
	if configPath != "" {
		v.SetConfigFile(configPath)
	} else {
		// 默认配置文件路径
		v.SetConfigName("config")
		v.SetConfigType("yaml")
		v.AddConfigPath("./configs")
		v.AddConfigPath(".")
	}

	// 设置环境变量前缀
	v.SetEnvPrefix("DAC")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	// 读取配置文件
	if err := v.ReadInConfig(); err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	// 验证配置
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("config validation failed: %w", err)
	}

	// Note: Don't log here, logger will be initialized after config is loaded

	return &cfg, nil
}

// Validate 验证配置
func (c *Config) Validate() error {
	// 验证服务器端口
	if c.Server.Port <= 0 || c.Server.Port > 65535 {
		return fmt.Errorf("invalid server port: %d", c.Server.Port)
	}

	// 验证服务模式
	if c.Server.Mode != "debug" && c.Server.Mode != "release" {
		return fmt.Errorf("invalid server mode: %s, must be 'debug' or 'release'", c.Server.Mode)
	}

	// 验证日志级别
	validLevels := map[string]bool{"debug": true, "info": true, "warn": true, "error": true}
	if !validLevels[strings.ToLower(c.Log.Level)] {
		return fmt.Errorf("invalid log level: %s", c.Log.Level)
	}

	// 验证日志格式
	if c.Log.Format != "json" && c.Log.Format != "text" {
		return fmt.Errorf("invalid log format: %s, must be 'json' or 'text'", c.Log.Format)
	}

	// 验证 JWT 配置
	if c.JWT.Secret == "" {
		return fmt.Errorf("jwt.secret is required")
	}
	if len(c.JWT.Secret) < 32 {
		return fmt.Errorf("jwt.secret must be at least 32 characters for security")
	}

	// 验证 Routing Agent configuration
	if c.RoutingAgent.BaseURL == "" {
		return fmt.Errorf("routing_agent.base_url is required")
	}

	// 验证database配置
	if c.Database.Driver == "" {
		return fmt.Errorf("database.driver is required")
	}
	if c.Database.Host == "" {
		return fmt.Errorf("database.host is required")
	}

	return nil
}

// GetServerAddr get服务器地址
func (c *Config) GetServerAddr() string {
	return fmt.Sprintf("%s:%d", c.Server.Host, c.Server.Port)
}

// GetReadTimeout get读超时时间
func (c *Config) GetReadTimeout() time.Duration {
	return c.Server.ReadTimeout
}

// GetWriteTimeout get写超时时间
func (c *Config) GetWriteTimeout() time.Duration {
	return c.Server.WriteTimeout
}
