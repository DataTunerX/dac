package handler

import (
	"context"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/common/utils"

	"github.com/lvyanru/dac-apiserver/pkg/k8s"
)

// HealthHandler 健康检查处理器
type HealthHandler struct {
	k8sClient *k8s.Client
}

// NewHealthHandler createnewof健康检查处理器
func NewHealthHandler(k8sClient *k8s.Client) *HealthHandler {
	return &HealthHandler{
		k8sClient: k8sClient,
	}
}

// Ping 基本健康检查
// @Summary Ping 健康检查
// @Description 检查服务is否run
// @Tags health
// @Produce json
// @Success 200 {object} map[string]string
// @Router /ping [get]
func (h *HealthHandler) Ping(ctx context.Context, c *app.RequestContext) {
	c.JSON(200, utils.H{
		"status":  "ok",
		"message": "pong",
	})
}

// Readiness 就绪检查
// @Summary 就绪检查
// @Description 检查服务is否就绪（包括依赖项）
// @Tags health
// @Produce json
// @Success 200 {object} map[string]interface{}
// @Failure 503 {object} map[string]interface{}
// @Router /health/ready [get]
func (h *HealthHandler) Readiness(ctx context.Context, c *app.RequestContext) {
	// 检查 Kubernetes 连接
	if err := h.k8sClient.HealthCheck(ctx); err != nil {
		c.JSON(503, utils.H{
			"status":     "not_ready",
			"kubernetes": "unhealthy",
			"error":      err.Error(),
		})
		return
	}

	c.JSON(200, utils.H{
		"status":     "ready",
		"kubernetes": "healthy",
	})
}

// Liveness 存活检查
// @Summary 存活检查
// @Description 检查服务is否存活
// @Tags health
// @Produce json
// @Success 200 {object} map[string]string
// @Router /health/live [get]
func (h *HealthHandler) Liveness(ctx context.Context, c *app.RequestContext) {
	c.JSON(200, utils.H{
		"status": "alive",
	})
}
