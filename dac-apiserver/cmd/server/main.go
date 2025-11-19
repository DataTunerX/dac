package main

import (
	"context"
	"log"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/cloudwego/hertz/pkg/app/server"
	"github.com/cloudwego/hertz/pkg/common/hlog"
	"github.com/cloudwego/hertz/pkg/network/netpoll"
	"github.com/spf13/cobra"

	_ "github.com/lvyanru/dac-apiserver/docs" // swagger docs
	"github.com/lvyanru/dac-apiserver/internal/config"
	"github.com/lvyanru/dac-apiserver/internal/handler"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/a2a"
	infradb "github.com/lvyanru/dac-apiserver/internal/infrastructure/database"
	"github.com/lvyanru/dac-apiserver/internal/infrastructure/k8s"
	"github.com/lvyanru/dac-apiserver/internal/router"
	"github.com/lvyanru/dac-apiserver/internal/usecase"
	dbpkg "github.com/lvyanru/dac-apiserver/pkg/database"
	k8sclient "github.com/lvyanru/dac-apiserver/pkg/k8s"
	"github.com/lvyanru/dac-apiserver/pkg/logger"
)

//	@title			DAC API Server
//	@version		0.1.0
//	@description	AI Agent management platform API service providing user management, chat conversations, and Kubernetes resource orchestration
//	@termsOfService	http://swagger.io/terms/

//	@contact.name	API Support
//	@contact.email	support@example.com

//	@license.name	Apache 2.0
//	@license.url	http://www.apache.org/licenses/LICENSE-2.0.html

//	@host		localhost:8080
//	@BasePath	/api/v1

//	@securityDefinitions.apikey	BearerAuth
//	@in							header
//	@name						Authorization
//	@description				JWT Token in format: Bearer {token}

var (
	cfgFile string
	version = "0.1.0"
)

var rootCmd = &cobra.Command{
	Use:   "dac-apiserver",
	Short: "DAC API Server for managing Kubernetes custom resources",
	Long: `DAC API Server is a high-performance HTTP API server built with Hertz framework.
It provides RESTful APIs for managing Kubernetes custom resources with CRUD operations.`,
	Version: version,
	Run:     runServer,
}

func init() {
	// Define flags
	rootCmd.PersistentFlags().StringVarP(&cfgFile, "config", "c", "configs/config.yaml", "path to config file")
}

func main() {
	if err := rootCmd.Execute(); err != nil {
		log.Fatal(err)
	}
}

func runServer(cmd *cobra.Command, args []string) {
	// Load configuration
	cfg, err := config.Load(cfgFile)
	if err != nil {
		log.Fatalf("failed to load config: %v", err)
	}

	// Initialize logger
	if err := logger.Setup(cfg.Log); err != nil {
		log.Fatalf("failed to initialize logger: %v", err)
	}

	// Log after logger is initialized
	slog.Info("config loaded successfully", "config_file", cfgFile)
	slog.Info("DAC API Server starting...",
		"version", version,
		"config", cfgFile,
	)

	// Setup Hertz to use slog
	hertzLogger := logger.NewHertzSlogAdapter(slog.Default())
	hlog.SetLogger(hertzLogger)
	hlog.SetLevel(hlog.LevelDebug)

	slog.Debug("hertz logger configured to use slog")

	// Initialize Kubernetes client
	k8sClient, err := k8sclient.NewClient()
	if err != nil {
		slog.Error("failed to create kubernetes client", "error", err)
		os.Exit(1)
	}

	// Check Kubernetes connection
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := k8sClient.HealthCheck(ctx); err != nil {
		slog.Warn("kubernetes health check failed, service may not work properly", "error", err)
	}

	// Initialize repositories, usecases, and handlers with dynamic client
	agentRepo := k8s.NewAgentContainerRepository(k8sClient)
	agentUsecase := usecase.NewAgentContainerUsecase(agentRepo)
	agentHandler := handler.NewAgentContainerHandler(agentUsecase)

	descriptorRepo := k8s.NewDataDescriptorRepository(k8sClient)
	descriptorUsecase := usecase.NewDataDescriptorUsecase(descriptorRepo)
	descriptorHandler := handler.NewDataDescriptorHandler(descriptorUsecase)

	// Initialize Database
	dbClient, err := dbpkg.NewClient(cfg.Database, slog.Default())
	if err != nil {
		slog.Error("failed to connect to database", "error", err)
		os.Exit(1)
	}

	slog.Info("database connected successfully")

	// Initialize User components
	userRepo := infradb.NewUserRepository(dbClient)
	userUsecase := usecase.NewUserUsecase(userRepo, slog.Default())
	userHandler := handler.NewUserHandler(userUsecase, cfg.JWT.Secret, slog.Default())

	slog.Info("user module initialized")

	// Initialize Chat components
	a2aClient := a2a.NewClient(
		cfg.RoutingAgent.BaseURL,
		cfg.RoutingAgent.Timeout,
		slog.Default(),
	)
	chatRepo := infradb.NewChatRepository(dbClient)
	chatUsecase := usecase.NewChatUsecase(
		a2aClient,
		chatRepo,
		userRepo, // Inject UserRepository
		slog.Default(),
	)
	chatHandler := handler.NewChatHandler(chatUsecase, slog.Default())

	slog.Info("handlers initialized with dynamic client")

	healthHandler := handler.NewHealthHandler(k8sClient)

	// Create Hertz server with performance optimization
	h := server.Default(
		server.WithHostPorts(cfg.GetServerAddr()),
		server.WithReadTimeout(cfg.GetReadTimeout()),
		server.WithWriteTimeout(cfg.GetWriteTimeout()),
		server.WithMaxRequestBodySize(cfg.Server.MaxRequestBodySize*1024*1024),
		server.WithTransport(netpoll.NewTransporter),
	)

	// Setup routes
	router.Setup(h, userHandler, agentHandler, descriptorHandler, chatHandler, healthHandler)

	// Start server
	slog.Info("server started successfully",
		"address", cfg.GetServerAddr(),
		"mode", cfg.Server.Mode,
	)

	// Graceful shutdown
	go func() {
		if err := h.Run(); err != nil {
			slog.Error("server run failed", "error", err)
			os.Exit(1)
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	slog.Info("shutting down server...")

	// Graceful shutdown with timeout
	ctx, cancel = context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := h.Shutdown(ctx); err != nil {
		slog.Error("server shutdown failed", "error", err)
		os.Exit(1)
	}

	// Close database connection
	if err := dbClient.Close(); err != nil {
		slog.Error("failed to close database", "error", err)
	} else {
		slog.Info("database closed successfully")
	}

	slog.Info("server stopped gracefully")
}
