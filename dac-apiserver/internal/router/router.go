package router

import (
	"github.com/cloudwego/hertz/pkg/app/server"
	"github.com/hertz-contrib/swagger"
	swaggerFiles "github.com/swaggo/files"

	"github.com/lvyanru/dac-apiserver/internal/handler"
	"github.com/lvyanru/dac-apiserver/internal/middleware"
)

// Setup sets up all routes
func Setup(
	h *server.Hertz,
	userHandler *handler.UserHandler,
	agentHandler *handler.AgentContainerHandler,
	descriptorHandler *handler.DataDescriptorHandler,
	chatHandler *handler.ChatHandler,
	healthHandler *handler.HealthHandler,
) {
	// Global middleware
	h.Use(middleware.Recovery())
	h.Use(middleware.Logger())
	h.Use(middleware.CORS())

	// Swagger API documentation (accessible in development environment)
	// Access at: http://localhost:8080/swagger/index.html
	h.GET("/swagger/*any", swagger.WrapHandler(swaggerFiles.Handler))

	// Health check routes (no authentication required)
	h.GET("/ping", healthHandler.Ping)
	h.GET("/health/ready", healthHandler.Readiness)
	h.GET("/health/live", healthHandler.Liveness)

	// API v1 routes
	apiV1 := h.Group("/api/v1")
	{
		// ============ Public routes (no authentication required) ============
		auth := apiV1.Group("/auth")
		{
			auth.POST("/register", userHandler.Register)
			auth.POST("/login", userHandler.Login)
			auth.POST("/refresh", userHandler.RefreshToken)
		}

		// ============ Protected routes (JWT authentication required) ============
		authorized := apiV1.Group("")
		authorized.Use(userHandler.AuthMiddleware())
		{
			// User management
			users := authorized.Group("/users")
			{
				users.GET("/me", userHandler.GetCurrentUser) // Get current user info
				users.GET("", userHandler.ListUsers)         // List users
				users.GET("/:id", userHandler.GetUser)       // Get user info
				users.DELETE("/:id", userHandler.DeleteUser) // Delete user
			}

			// Agent Container routes - all namespaces (cluster-scoped)
			authorized.GET("/agents", agentHandler.ListAll)

			// Agent Container routes - namespaced
			agents := authorized.Group("/namespaces/:namespace/agents")
			{
				agents.POST("", agentHandler.Create)
				agents.GET("", agentHandler.List)
				agents.GET("/:name", agentHandler.Get)
				agents.PUT("/:name", agentHandler.Update)
				agents.DELETE("/:name", agentHandler.Delete)
			}

			// Data Descriptor routes - all namespaces (cluster-scoped)
			authorized.GET("/descriptors", descriptorHandler.ListAll)

			// Data Descriptor routes - namespaced
			descriptors := authorized.Group("/namespaces/:namespace/descriptors")
			{
				descriptors.POST("", descriptorHandler.Create)
				descriptors.GET("", descriptorHandler.List)
				descriptors.GET("/:name", descriptorHandler.Get)
				descriptors.PUT("/:name", descriptorHandler.Update)
				descriptors.DELETE("/:name", descriptorHandler.Delete)
			}
		}
	}

	// OpenAI-compatible API (protected)
	v1 := h.Group("/v1")
	v1.Use(userHandler.AuthMiddleware())
	{
		// Chat completions (OpenAI format)
		// POST /v1/chat/completions
		v1.POST("/chat/completions", chatHandler.CreateChatCompletion)
	}
}
