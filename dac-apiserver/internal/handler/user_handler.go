package handler

import (
	"context"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/protocol"
	"github.com/cloudwego/hertz/pkg/protocol/consts"
	"github.com/hertz-contrib/jwt"

	"github.com/lvyanru/dac-apiserver/internal/config"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// UserHandler handles user-related HTTP requests
type UserHandler struct {
	usecase        domain.UserUsecase
	authMiddleware *jwt.HertzJWTMiddleware
	logger         *slog.Logger
}

// NewUserHandler creates a new user handler
func NewUserHandler(usecase domain.UserUsecase, jwtCfg config.JWTConfig, logger *slog.Logger) *UserHandler {
	timeout := jwtCfg.Timeout
	if timeout == 0 {
		timeout = 15 * time.Minute
	}
	maxRefresh := jwtCfg.MaxRefresh
	if maxRefresh == 0 {
		maxRefresh = 168 * time.Hour
	}

	authMiddleware, err := jwt.New(&jwt.HertzJWTMiddleware{
		Realm:       "dac-api",
		Key:         []byte(jwtCfg.Secret),
		Timeout:     timeout,
		MaxRefresh:  maxRefresh,
		IdentityKey: "user_id",

		// Login authentication logic
		Authenticator: func(ctx context.Context, c *app.RequestContext) (interface{}, error) {
			var loginReq dto.LoginRequest
			if err := c.BindJSON(&loginReq); err != nil {
				return nil, jwt.ErrMissingLoginValues
			}

			// Call usecase for verification
			user, err := usecase.Login(ctx, loginReq.Username, loginReq.Password)
			if err != nil {
				logger.Error("login failed", "username", loginReq.Username, "error", err)
				return nil, jwt.ErrFailedAuthentication
			}

			// Store user info in context for LoginResponse
			c.Set("user", user)
			return user, nil
		},

		// Token Payload - write user info into JWT
		PayloadFunc: func(data interface{}) jwt.MapClaims {
			if user, ok := data.(*entity.User); ok {
				return jwt.MapClaims{
					"user_id":  user.ID,
					"username": user.Username,
					"role":     user.Role,
				}
			}
			return jwt.MapClaims{}
		},

		// Extract identity information from Token
		IdentityHandler: func(ctx context.Context, c *app.RequestContext) interface{} {
			claims := jwt.ExtractClaims(ctx, c)
			if userID, ok := claims["user_id"].(string); ok {
				// Store user_id in RequestContext for all handlers to use
				c.Set("user_id", userID)
				if role, ok := claims["role"].(string); ok {
					c.Set("role", role)
				}
				return userID
			}
			return ""
		},

		// Authorization check (access allowed with valid token)
		Authorizator: func(data interface{}, ctx context.Context, c *app.RequestContext) bool {
			return data != nil
		},

		// Unauthorized handler
		Unauthorized: func(ctx context.Context, c *app.RequestContext, code int, message string) {
			c.JSON(code, map[string]any{
				"code":    "UNAUTHORIZED",
				"message": message,
			})
		},

		// Login response
		LoginResponse: func(ctx context.Context, c *app.RequestContext, code int, _ string, expire time.Time) {
			// Get user info from context
			user, exists := c.Get("user")
			if !exists {
				c.JSON(consts.StatusInternalServerError, map[string]any{
					"code":    "INTERNAL_ERROR",
					"message": "failed to get user info",
				})
				return
			}
			userEntity := user.(*entity.User)

			c.JSON(consts.StatusOK, map[string]any{
				"code": "SUCCESS",
				"data": dto.LoginResponse{
					Expire: expire.Format(time.RFC3339),
					User:   dto.ToUserResponse(userEntity),
				},
			})
		},

		// Refresh response
		RefreshResponse: func(ctx context.Context, c *app.RequestContext, code int, _ string, expire time.Time) {
			c.JSON(consts.StatusOK, map[string]any{
				"code": "SUCCESS",
				"data": map[string]any{
					"expire": expire.Format(time.RFC3339),
				},
			})
		},

		// Logout response
		LogoutResponse: func(ctx context.Context, c *app.RequestContext, code int) {
			c.JSON(consts.StatusOK, map[string]any{
				"code": "SUCCESS",
			})
		},

		SendCookie:     true,
		CookieHTTPOnly: true,
		CookieName:     "dac_token",
		CookieSameSite: protocol.CookieSameSiteLaxMode,
		CookieMaxAge:   maxRefresh,
		SecureCookie:   jwtCfg.CookieSecure,
		CookieDomain:   jwtCfg.CookieDomain,

		TokenLookup:   "header: Authorization, cookie: dac_token",
		TokenHeadName: "Bearer",
		TimeFunc:      time.Now,
	})

	if err != nil {
		logger.Error("failed to create jwt middleware", "error", err)
		panic(err)
	}

	return &UserHandler{
		usecase:        usecase,
		authMiddleware: authMiddleware,
		logger:         logger,
	}
}

// AuthMiddleware returns JWT authentication middleware (for route protection)
func (h *UserHandler) AuthMiddleware() app.HandlerFunc {
	return h.authMiddleware.MiddlewareFunc()
}

// Register handles user registration
//
//	@Summary		User registration
//	@Description	createnewuser账号
//	@Tags			认证
//	@Accept			json
//	@Produce		json
//	@Param			request	body		dto.RegisterRequest	true	"注册信息"
//	@Success		200		{object}	dto.UserResponse		"Registered successfully"
//	@Failure		400		{object}	map[string]string		"Invalid request parameters"
//	@Failure		409		{object}	map[string]string		"user名已exists"
//	@Router			/auth/register [post]
func (h *UserHandler) Register(ctx context.Context, c *app.RequestContext) {
	var req dto.RegisterRequest
	if err := c.BindJSON(&req); err != nil {
		h.logger.Error("invalid register request", "error", err)
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	user, err := h.usecase.Register(ctx, req.Username, req.Password)
	if err != nil {
		h.logger.Error("register failed", "error", err)
		ErrorResponse(c, err)
		return
	}

	// Return user info (excluding password)
	SuccessResponse(c, dto.ToUserResponse(user))
}

// Login handles user login (using Hertz JWT LoginHandler)
//
//	@Summary		User login
//	@Description	用户名密码登录，通过 HttpOnly cookie 建立会话
//	@Tags			认证
//	@Accept			json
//	@Produce		json
//	@Param			request	body		dto.LoginRequest		true	"登录信息"
//	@Success		200		{object}	dto.LoginResponse		"Login successful"
//	@Failure		400		{object}	map[string]string		"Invalid request parameters"
//	@Failure		401		{object}	map[string]string		"Invalid username or password"
//	@Router			/auth/login [post]
func (h *UserHandler) Login(ctx context.Context, c *app.RequestContext) {
	h.authMiddleware.LoginHandler(ctx, c)
}

// RefreshToken refreshes the authentication token
// POST /api/v1/auth/refresh
func (h *UserHandler) RefreshToken(ctx context.Context, c *app.RequestContext) {
	h.authMiddleware.RefreshHandler(ctx, c)
}

// Logout clears the JWT cookie
// POST /api/v1/auth/logout
func (h *UserHandler) Logout(ctx context.Context, c *app.RequestContext) {
	h.authMiddleware.LogoutHandler(ctx, c)
}

// GetCurrentUser retrieves the currently logged-in user's information
//
//	@Summary		get当前user
//	@Description	Get detailed information of current logged-in user
//	@Tags			User Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Success		200	{object}	dto.UserResponse	"User information"
//	@Failure		401	{object}	map[string]string	"Unauthorized"
//	@Router			/users/me [get]
func (h *UserHandler) GetCurrentUser(ctx context.Context, c *app.RequestContext) {
	userID, ok := GetUserIDFromContext(c, h.logger)
	if !ok {
		ErrorResponse(c, domain.ErrUnauthorized)
		return
	}

	user, err := h.usecase.GetUser(ctx, userID)
	if err != nil {
		h.logger.Error("failed to get current user", "error", err, "user_id", userID)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, dto.ToUserResponse(user))
}

// GetUser retrieves user information (admin function)
// GET /api/v1/users/:id
func (h *UserHandler) GetUser(ctx context.Context, c *app.RequestContext) {
	userID := c.Param("id")
	if userID == "" {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	user, err := h.usecase.GetUser(ctx, userID)
	if err != nil {
		h.logger.Error("failed to get user", "error", err, "user_id", userID)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, dto.ToUserResponse(user))
}

// ListUsers retrieves a paginated list of users
//
//	@Summary		User list
//	@Description	分页查询User list（需要认证）
//	@Tags			User Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			page		query		int						false	"页码"			default(1)
//	@Param			page_size	query		int						false	"每页数量"		default(20)
//	@Success		200			{object}	dto.UserListResponse	"User list"
//	@Failure		401			{object}	map[string]string		"Unauthorized"
//	@Router			/users [get]
func (h *UserHandler) ListUsers(ctx context.Context, c *app.RequestContext) {
	// Parse pagination parameters
	page, err := strconv.Atoi(c.DefaultQuery("page", "1"))
	if err != nil || page < 1 {
		page = 1
	}

	pageSize, err := strconv.Atoi(c.DefaultQuery("page_size", "20"))
	if err != nil || pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}

	users, total, err := h.usecase.ListUsers(ctx, page, pageSize)
	if err != nil {
		h.logger.Error("failed to list users", "error", err)
		ErrorResponse(c, err)
		return
	}

	// Convert to response format
	SuccessResponse(c, dto.ToUserListResponse(users, total, page, pageSize))
}

// DeleteUser deletes a user
//
//	@Summary		Delete user
//	@Description	软删除指定user（标记为已删除，不可恢复）
//	@Tags			User Management
//	@Accept			json
//	@Produce		json
//	@Security		BearerAuth
//	@Param			id	path		string				true	"userID"
//	@Success		200	{object}	map[string]string	"Deleted successfully"
//	@Failure		400	{object}	map[string]string	"Invalid request parameters"
//	@Failure		401	{object}	map[string]string	"Unauthorized"
//	@Failure		404	{object}	map[string]string	"User not found"
//	@Router			/users/{id} [delete]
func (h *UserHandler) DeleteUser(ctx context.Context, c *app.RequestContext) {
	userID := c.Param("id")
	if userID == "" {
		ErrorResponse(c, domain.ErrInvalidInput)
		return
	}

	// Prevent deleting yourself
	currentUserID, ok := GetUserIDFromContext(c, h.logger)
	if !ok {
		ErrorResponse(c, domain.ErrUnauthorized)
		return
	}
	if userID == currentUserID {
		ErrorResponse(c, domain.NewInvalidInputError("cannot delete yourself"))
		return
	}

	if err := h.usecase.DeleteUser(ctx, userID); err != nil {
		h.logger.Error("failed to delete user", "error", err, "user_id", userID)
		ErrorResponse(c, err)
		return
	}

	SuccessResponse(c, map[string]string{
		"message": fmt.Sprintf("user %s deleted successfully", userID),
	})
}
