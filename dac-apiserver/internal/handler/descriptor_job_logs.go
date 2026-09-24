package handler

import (
	"bufio"
	"context"
	"io"
	"log/slog"
	"regexp"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/protocol/consts"
	"github.com/cloudwego/hertz/pkg/protocol/sse"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// dataSinkerJobContainer is the only container whose logs the data-source page streams.
// Sibling containers on the same pod (data-services, data-sinker-status) are ignored.
const dataSinkerJobContainer = "data-sinker-job"

const sinkerJobLogTailLines int64 = 500

// StreamJobLogs follows the data-sinker-job container log for a data descriptor.
// The deployment is named dd-{name} and its pods are labeled data={name}.
// The route sits outside /descriptors/** so descriptor:read does not grant it.
func (h *DataDescriptorHandler) StreamJobLogs(ctx context.Context, c *app.RequestContext) {
	namespace := c.Param("namespace")
	name := c.Param("name")

	if !verifyTenantNamespaceAccess(c, h.logger, namespace) {
		ErrorResponse(c, domain.ErrForbidden)
		return
	}
	if !isSafeK8sName(namespace) || !isSafeK8sName(name) {
		ErrorResponse(c, domain.NewInvalidInputError("invalid namespace or name"))
		return
	}
	if h.kube == nil {
		h.logger.Error("kubernetes client is not configured for job logs")
		ErrorResponse(c, domain.NewInternalError(nil))
		return
	}

	selector := labels.Set{"data": name}.AsSelector().String()
	pods, err := h.kube.CoreV1().Pods(namespace).List(ctx, metav1.ListOptions{LabelSelector: selector})
	if err != nil {
		h.logger.Error("list sinker job pods failed", "namespace", namespace, "name", name, "error", err)
		ErrorResponse(c, domain.NewInternalError(err))
		return
	}
	pod := selectSinkerJobPod(pods.Items)
	if pod == nil {
		ErrorResponse(c, sinkerJobUnavailable())
		return
	}

	tail := sinkerJobLogTailLines
	stream, err := h.kube.CoreV1().Pods(namespace).GetLogs(pod.Name, &corev1.PodLogOptions{
		Container: dataSinkerJobContainer,
		Follow:    true,
		TailLines: &tail,
	}).Stream(ctx)
	if err != nil {
		h.logger.Warn("open sinker job log stream failed",
			"namespace", namespace, "name", name, "pod", pod.Name, "error", err)
		ErrorResponse(c, sinkerJobUnavailable())
		return
	}
	defer stream.Close()
	// Unblock the log read when the request is cancelled. The closer is
	// stopped when the handler returns so it does not outlive the stream.
	stop := make(chan struct{})
	defer close(stop)
	go func() {
		select {
		case <-ctx.Done():
			stream.Close()
		case <-stop:
		}
	}()

	h.logger.Info("streaming sinker job logs",
		"namespace", namespace, "name", name, "pod", pod.Name, "container", dataSinkerJobContainer)

	c.SetStatusCode(consts.StatusOK)
	c.Header("X-Accel-Buffering", "no")
	writer := sse.NewWriter(c)
	_ = writer.WriteEvent("", "meta", []byte(pod.Name))
	streamJobLogLines(ctx, h.logger, writer, stream)
}

func streamJobLogLines(ctx context.Context, logger *slog.Logger, writer *sse.Writer, r io.Reader) {
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for scanner.Scan() {
		if ctx.Err() != nil {
			return
		}
		// Scanner reuses its buffer on the next Scan, so copy before writing.
		line := append([]byte(nil), scanner.Bytes()...)
		if err := writer.WriteEvent("", "log", line); err != nil {
			return
		}
	}
	if err := scanner.Err(); err != nil && ctx.Err() == nil {
		logger.Warn("sinker job log stream ended", "error", err)
		_ = writer.WriteEvent("", "error", []byte("日志流已中断"))
		return
	}
	_ = writer.WriteEvent("", "end", []byte("closed"))
}

func sinkerJobUnavailable() error {
	return &domain.DomainError{
		Code:    "NOT_FOUND",
		Message: "同步任务尚未就绪，或已经结束并被清理",
		Err:     domain.ErrNotFound,
	}
}

// selectSinkerJobPod picks the pod that still has the job container.
// Running pods win over pending or finished ones; among equals, the newest wins.
func selectSinkerJobPod(pods []corev1.Pod) *corev1.Pod {
	var best *corev1.Pod
	for i := range pods {
		pod := &pods[i]
		if pod.DeletionTimestamp != nil {
			continue
		}
		if !podHasContainer(pod, dataSinkerJobContainer) {
			continue
		}
		if best == nil || sinkerPodBetter(pod, best) {
			best = pod
		}
	}
	return best
}

func sinkerPodBetter(candidate, current *corev1.Pod) bool {
	cr, rr := sinkerPodRank(candidate), sinkerPodRank(current)
	if cr != rr {
		return cr > rr
	}
	return candidate.CreationTimestamp.After(current.CreationTimestamp.Time)
}

func sinkerPodRank(pod *corev1.Pod) int {
	switch pod.Status.Phase {
	case corev1.PodRunning:
		return 3
	case corev1.PodPending:
		return 2
	default:
		return 1
	}
}

func podHasContainer(pod *corev1.Pod, name string) bool {
	for _, c := range pod.Spec.Containers {
		if c.Name == name {
			return true
		}
	}
	return false
}

var k8sNamePattern = regexp.MustCompile(`^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`)

func isSafeK8sName(s string) bool {
	if len(s) == 0 || len(s) > 63 {
		return false
	}
	return k8sNamePattern.MatchString(s)
}
