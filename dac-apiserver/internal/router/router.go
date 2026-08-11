package router

import (
	"context"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/app/server"
	"github.com/hertz-contrib/swagger"
	swaggerFiles "github.com/swaggo/files"

	"github.com/lvyanru/dac-apiserver/internal/handler"
	"github.com/lvyanru/dac-apiserver/internal/middleware"

	"github.com/casbin/casbin/v2"
)

// Setup sets up all routes
func Setup(
	h *server.Hertz,
	userHandler *handler.UserHandler,
	agentHandler *handler.AgentContainerHandler,
	descriptorHandler *handler.DataDescriptorHandler,
	semanticDomainHandler *handler.SemanticDomainHandler,
	discoveryHandler *handler.DiscoveryHandler,
	probeHandler *handler.DataSourceProbeHandler,
	chatHandler *handler.ChatHandler,
	configMapHandler *handler.ConfigMapHandler,
	systemConfigHandler *handler.SystemConfigHandler,
	agentRegistryHandler *handler.AgentRegistryHandler,
	skillHubHandler *handler.SkillHubHandler,
	namespaceHandler *handler.NamespaceHandler,
	semanticGroupHandler *handler.SemanticGroupHandler,
	ddGroupRelationHandler *handler.DDGroupRelationHandler,
	knowledgeGraphHandler *handler.KnowledgeGraphHandler,
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

	// Initialize Casbin Enforcer
	enforcer, err := casbin.NewEnforcer("configs/authz/model.conf", "configs/authz/policy.csv")
	if err != nil {
		panic(err)
	}

	// Custom Casbin Middleware for Path/Method Authorization
	// Note: We use a custom middleware because hertz-contrib/casbin does not support
	// automatic RoutePermission (Path/Method matching) out of the box like Fiber's middleware.
	authzMiddleware := func(ctx context.Context, c *app.RequestContext) {
		path := string(c.Request.URI().Path())
		method := string(c.Request.Method())

		// Get current user role from context (set by JWT middleware)
		role := "anonymous"
		if v, exists := c.Get("role"); exists {
			role = v.(string)
		}

		// Enforce policy: sub, obj, act
		allowed, err := enforcer.Enforce(role, path, method)
		if err != nil {
			c.AbortWithStatusJSON(500, map[string]string{"message": "error checking permissions"})
			return
		}
		if !allowed {
			c.AbortWithStatusJSON(403, map[string]string{"message": "forbidden"})
			return
		}

		c.Next(ctx)
	}

	// API v1 routes
	apiV1 := h.Group("/api/v1")
	{
		// ============ Public routes (no authentication required) ============
		auth := apiV1.Group("/auth")
		{
			auth.POST("/register", userHandler.Register)
			auth.POST("/login", userHandler.Login)
			auth.POST("/refresh", userHandler.RefreshToken)
			auth.POST("/logout", userHandler.Logout)
		}

		// ============ Protected routes (JWT authentication required) ============
		authorized := apiV1.Group("")
		authorized.Use(userHandler.AuthMiddleware())

		// Use custom middleware
		authorized.Use(authzMiddleware)

		{
			// Namespaces (cluster-scoped)
			authorized.GET("/namespaces", namespaceHandler.List)
			authorized.GET("/environment/gpu", healthHandler.GPUAvailability)

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
			// Semantic Domain routes (data-services integration)
			semanticDomains := authorized.Group("/semantic-domains")
			{
				semanticDomains.POST("", semanticDomainHandler.Create)
				semanticDomains.POST("/batch", semanticDomainHandler.BatchCreate)
				semanticDomains.POST("/search/by-dd", semanticDomainHandler.SearchByDD)
				semanticDomains.GET("/status/count", semanticDomainHandler.Count)

				semanticDomains.GET("/:id", semanticDomainHandler.Get)
				semanticDomains.GET("/:id/exists", semanticDomainHandler.Exists)
				semanticDomains.PUT("/:id", semanticDomainHandler.Update)
				semanticDomains.DELETE("/:id", semanticDomainHandler.Delete)

				semanticDomains.DELETE("/dd-info/:dd_namespace/:dd_name", semanticDomainHandler.DeleteByDDInfo)
				semanticDomains.GET("/dd-info/:dd_namespace/:dd_name/exists", semanticDomainHandler.ExistsByDDInfo)
			}

			// Data Descriptor routes - namespaced
			descriptors := authorized.Group("/namespaces/:namespace/descriptors")
			{
				descriptors.POST("", descriptorHandler.Create)
				descriptors.GET("", descriptorHandler.List)
				descriptors.GET("/:name", descriptorHandler.Get)
				descriptors.GET("/:name/signature", descriptorHandler.GetSignature)
				descriptors.GET("/:name/semantic-domain", descriptorHandler.GetSemanticDomain)
				descriptors.PUT("/:name", descriptorHandler.Update)
				descriptors.POST("/:name/resync", descriptorHandler.RequestResync)
				descriptors.DELETE("/:name", descriptorHandler.Delete)

				// Knowledge Fragments Management
				descriptors.GET("/:name/knowledge", descriptorHandler.GetKnowledge)
				descriptors.POST("/:name/knowledge/search", descriptorHandler.SearchKnowledge)
				descriptors.POST("/:name/knowledge/delete", descriptorHandler.DeleteKnowledge)
			}

			// ConfigMap routes - namespaced (for LLM / prompts management)
			configmaps := authorized.Group("/namespaces/:namespace/configmaps")
			{
				configmaps.POST("", configMapHandler.Create)
				configmaps.GET("", configMapHandler.List)
				configmaps.GET("/:name", configMapHandler.Get)
				configmaps.PUT("/:name", configMapHandler.Update)
				configmaps.DELETE("/:name", configMapHandler.Delete)
			}

			// System configuration (cluster-wide dac-configuration / dd-configuration)
			systemConfigs := authorized.Group("/system/configurations")
			{
				systemConfigs.GET("", systemConfigHandler.List)
				systemConfigs.GET("/:name/versions/:version", systemConfigHandler.GetVersion)
				systemConfigs.GET("/:name/versions", systemConfigHandler.ListVersions)
				systemConfigs.GET("/:name", systemConfigHandler.Get)
				systemConfigs.PUT("/:name", systemConfigHandler.Update)
			}

			// Observability: agent registries
			observability := authorized.Group("/observability")
			{
				agentRegistries := observability.Group("/agent-registries")
				{
					agentRegistries.GET("", agentRegistryHandler.ListRegistries)
					agentRegistries.GET("/:registry/agents", agentRegistryHandler.ListAgents)
				}
			}

			// Skill Hub (skill zip registry BFF)
			skills := authorized.Group("/skills")
			{
				skills.POST("/reload", skillHubHandler.Reload)
				skills.GET("/namespaces", skillHubHandler.ListNamespaces)
				skills.POST("/namespaces", skillHubHandler.CreateNamespace)
				skills.GET("/namespaces/:ns/exists", skillHubHandler.NamespaceExists)
				skills.DELETE("/namespaces/:ns", skillHubHandler.DeleteNamespace)
				skills.GET("/namespaces/:ns/skills", skillHubHandler.ListSkills)
				skills.POST("/namespaces/:ns/skills/create", skillHubHandler.CreateSkill)
				skills.POST("/namespaces/:ns/skills", skillHubHandler.UploadSkill)
				skills.GET("/namespaces/:ns/skills/:name", skillHubHandler.GetSkill)
				skills.GET("/namespaces/:ns/skills/:name/download", skillHubHandler.DownloadSkill)
				skills.DELETE("/namespaces/:ns/skills/:name", skillHubHandler.DeleteSkill)
			}

			// Chat History routes
			chat := authorized.Group("/chat")
			{
				chat.GET("/conversations", chatHandler.ListConversations)       // List recent conversations
				chat.GET("/conversations/:run_id", chatHandler.GetConversation) // Get conversation history
			}

			// Discovery routes (scan IP -> open ports/services)
			discovery := authorized.Group("/discovery")
			{
				discovery.POST("/scans", discoveryHandler.StartScan)
				discovery.GET("/scans", discoveryHandler.ListScans)
				discovery.GET("/scans/:id", discoveryHandler.GetScan)
				discovery.PATCH("/scans/:id", discoveryHandler.UpdateScan)
				discovery.DELETE("/scans/:id", discoveryHandler.DeleteScan)
			}

			// DataSource probe routes (synchronous connectivity test + database listing)
			datasources := authorized.Group("/datasources")
			{
				datasources.POST("/probe", probeHandler.Probe)
				datasources.GET("/probe/types", probeHandler.SupportedTypes)
			}

			// Semantic Group routes (data-services integration)
			semanticGroups := authorized.Group("/semantic-groups")
			{
				semanticGroups.POST("", semanticGroupHandler.Create)
				semanticGroups.POST("/batch", semanticGroupHandler.BatchCreate)
				semanticGroups.GET("", semanticGroupHandler.List)
				semanticGroups.GET("/roots", semanticGroupHandler.ListRoots)
				semanticGroups.GET("/member-tasks/:taskId", semanticGroupHandler.GetMemberTask)
				semanticGroups.GET("/status/count", semanticGroupHandler.Count)
				semanticGroups.GET("/:id/with-members", semanticGroupHandler.GetWithMembers)
				semanticGroups.GET("/:id", semanticGroupHandler.Get)
				semanticGroups.GET("/:id/exists", semanticGroupHandler.Exists)
				semanticGroups.PUT("/:id", semanticGroupHandler.Update)
				semanticGroups.DELETE("/:id", semanticGroupHandler.Delete)
				semanticGroups.POST("/:id/members", semanticGroupHandler.AddMember)
				semanticGroups.POST("/:id/members/remove", semanticGroupHandler.RemoveMember)
			}

			// DD Group Relation routes (list + delete relation row in data-services)
			ddGroupRelations := authorized.Group("/dd-group-relations")
			{
				ddGroupRelations.GET("/group/:group_id", ddGroupRelationHandler.ListByGroup)
				ddGroupRelations.GET("/sd/:sd_id", ddGroupRelationHandler.ListBySD)
				ddGroupRelations.DELETE("/:id", ddGroupRelationHandler.DeleteByID)
			}

			// Knowledge Graph routes (data-services integration)
			knowledgeGraph := authorized.Group("/knowledge-graph")
			{
				knowledgeGraph.POST("/add-with-source", knowledgeGraphHandler.AddWithSource)
				knowledgeGraph.POST("/search-with-source", knowledgeGraphHandler.SearchWithSource)
				knowledgeGraph.POST("/get-graph-by-source", knowledgeGraphHandler.GetGraphBySource)
				knowledgeGraph.DELETE("/delete-with-source", knowledgeGraphHandler.DeleteWithSource)
			}
		}
	}

	// OpenAI-compatible API (protected)
	v1 := h.Group("/v1")
	v1.Use(userHandler.AuthMiddleware())
	// Use Casbin middleware for v1 as well if needed, or leave open for now.
	// For Chat, usually we allow all authenticated users.
	// The policy for chat is defined as: p, user, /v1/chat/completions, POST
	// So we should apply it here too.
	v1.Use(authzMiddleware)
	{
		// Chat completions (OpenAI format)
		// POST /v1/chat/completions
		v1.POST("/chat/completions", chatHandler.CreateChatCompletion)
	}
}
