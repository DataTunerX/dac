package database

import (
	"context"
	"database/sql"
	"fmt"
	"log/slog"
	"time"

	entsql "entgo.io/ent/dialect/sql"
	"github.com/lvyanru/dac-apiserver/internal/config"
	"github.com/lvyanru/dac-apiserver/internal/ent"

	_ "github.com/go-sql-driver/mysql"
)

// NewSQLDB opens the MySQL connection pool. It is exported so that components
// which need raw SQL (the TDB pipeline run store) can share the same pool as
// the ent client instead of opening a second one.
func NewSQLDB(cfg config.DatabaseConfig) (*sql.DB, error) {
	// 构造 DSN
	dsn := fmt.Sprintf("%s:%s@tcp(%s:%d)/%s?parseTime=True&loc=Local&charset=utf8mb4",
		cfg.User,
		cfg.Password,
		cfg.Host,
		cfg.Port,
		cfg.Database,
	)

	// 打开 MySQL 连接
	db, err := sql.Open(cfg.Driver, dsn)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// 配置连接池
	db.SetMaxOpenConns(cfg.MaxOpenConns)
	db.SetMaxIdleConns(cfg.MaxIdleConns)
	db.SetConnMaxLifetime(cfg.ConnMaxLifetime)

	// Ping 测试连接
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	return db, nil
}

// NewClientWithDB wraps an already-open pool in an ent client and runs the
// schema auto-migration.
func NewClientWithDB(db *sql.DB, cfg config.DatabaseConfig, logger *slog.Logger) (*ent.Client, error) {
	// create ent 驱动
	drv := entsql.OpenDB(cfg.Driver, db)
	client := ent.NewClient(ent.Driver(drv))

	// 自动迁移 schema
	if err := client.Schema.Create(context.Background()); err != nil {
		client.Close()
		return nil, fmt.Errorf("failed to create schema: %w", err)
	}

	logger.Info("database connected",
		"driver", cfg.Driver,
		"host", cfg.Host,
		"database", cfg.Database,
		"max_open_conns", cfg.MaxOpenConns,
		"max_idle_conns", cfg.MaxIdleConns,
	)

	return client, nil
}

// NewClient createdatabaseclient
func NewClient(cfg config.DatabaseConfig, logger *slog.Logger) (*ent.Client, error) {
	db, err := NewSQLDB(cfg)
	if err != nil {
		return nil, err
	}
	return NewClientWithDB(db, cfg, logger)
}

// Close 关闭database连接
func Close(client *ent.Client, logger *slog.Logger) error {
	if err := client.Close(); err != nil {
		logger.Error("failed to close database", "error", err)
		return err
	}
	logger.Info("database closed")
	return nil
}
