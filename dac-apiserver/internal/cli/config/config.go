package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// Config stores CLI configuration
type Config struct {
	Server      string `json:"server"`       // API Server address
	AccessToken string `json:"access_token"` // JWT access token
	Username    string `json:"username"`     // Current logged-in username
	UserID      string `json:"user_id"`      // Current logged-in user ID (UUID)
}

// GetConfigPath returns the configuration file path (~/.dactl/config.json)
func GetConfigPath() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("failed to get home directory: %w", err)
	}

	configDir := filepath.Join(home, ".dactl")
	configFile := filepath.Join(configDir, "config.json")

	return configFile, nil
}

// Load loads configuration from file
func Load() (*Config, error) {
	configFile, err := GetConfigPath()
	if err != nil {
		return nil, err
	}

	// If config file doesn't exist, return default config
	if _, err := os.Stat(configFile); os.IsNotExist(err) {
		return &Config{
			Server: "http://localhost:8080",
		}, nil
	}

	data, err := os.ReadFile(configFile)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("failed to parse config file: %w", err)
	}

	// Use default server if not set
	if cfg.Server == "" {
		cfg.Server = "http://localhost:8080"
	}

	return &cfg, nil
}

// Save saves configuration to file
func (c *Config) Save() error {
	configFile, err := GetConfigPath()
	if err != nil {
		return err
	}

	// Ensure config directory exists
	configDir := filepath.Dir(configFile)
	if err := os.MkdirAll(configDir, 0755); err != nil {
		return fmt.Errorf("failed to create config directory: %w", err)
	}

	// Marshal config
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	// Write to file (0600 permission, user read/write only)
	if err := os.WriteFile(configFile, data, 0600); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}

	return nil
}

// IsAuthenticated checks if user is logged in
func (c *Config) IsAuthenticated() bool {
	return c.AccessToken != ""
}
