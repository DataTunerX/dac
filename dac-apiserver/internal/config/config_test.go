package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestLoad_SkillHubTimeoutDefault(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "config.yaml")
	content := `
server:
  port: 8080
jwt:
  secret: "test-secret"
database:
  driver: "mysql"
  host: "127.0.0.1"
  port: 3306
  user: "u"
  password: "p"
  database: "db"
`
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.SkillHub.Timeout != 120*time.Second {
		t.Fatalf("timeout=%v", cfg.SkillHub.Timeout)
	}
}
