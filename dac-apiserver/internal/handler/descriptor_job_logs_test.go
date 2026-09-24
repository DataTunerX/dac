package handler

import (
	"io"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/cloudwego/hertz/pkg/app/server"
	"github.com/cloudwego/hertz/pkg/common/ut"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

func TestSelectSinkerJobPodPrefersRunningOverNewerPending(t *testing.T) {
	now := time.Now()
	pods := []corev1.Pod{
		sinkerPod("new-pending", corev1.PodPending, now, true, false),
		sinkerPod("old-running", corev1.PodRunning, now.Add(-time.Hour), true, false),
		sinkerPod("no-job", corev1.PodRunning, now, false, false),
	}
	got := selectSinkerJobPod(pods)
	if got == nil || got.Name != "old-running" {
		t.Fatalf("got %#v, want old-running", got)
	}
}

func TestSelectSinkerJobPodPicksNewestRunning(t *testing.T) {
	now := time.Now()
	pods := []corev1.Pod{
		sinkerPod("older", corev1.PodRunning, now.Add(-time.Minute), true, false),
		sinkerPod("newer", corev1.PodRunning, now, true, false),
	}
	got := selectSinkerJobPod(pods)
	if got == nil || got.Name != "newer" {
		t.Fatalf("got %#v, want newer", got)
	}
}

func TestSelectSinkerJobPodSkipsTerminating(t *testing.T) {
	now := time.Now()
	pods := []corev1.Pod{
		sinkerPod("going-away", corev1.PodRunning, now, true, true),
		sinkerPod("kept", corev1.PodPending, now.Add(-time.Minute), true, false),
	}
	got := selectSinkerJobPod(pods)
	if got == nil || got.Name != "kept" {
		t.Fatalf("got %#v, want kept", got)
	}
}

func TestSelectSinkerJobPodNone(t *testing.T) {
	if got := selectSinkerJobPod(nil); got != nil {
		t.Fatalf("got %s, want nil", got.Name)
	}
}

func TestStreamJobLogsRejectsUnsafeName(t *testing.T) {
	body, code := performJobLogs(t, fake.NewSimpleClientset(), "default", "orders,other=evil")
	if code != 400 {
		t.Fatalf("status %d body %s", code, body)
	}
}

func TestStreamJobLogsMissingPod(t *testing.T) {
	body, code := performJobLogs(t, fake.NewSimpleClientset(), "default", "orders")
	if code != 404 {
		t.Fatalf("status %d body %s", code, body)
	}
	if !strings.Contains(body, "同步任务尚未就绪") {
		t.Fatalf("body %s", body)
	}
}

func TestStreamJobLogsIgnoresPodsWithoutJobContainer(t *testing.T) {
	pod := sinkerPod("dd-orders-other", corev1.PodRunning, time.Now(), false, false)
	pod.Namespace = "default"
	pod.Labels = map[string]string{"data": "orders"}
	body, code := performJobLogs(t, fake.NewSimpleClientset(&pod), "default", "orders")
	if code != 404 {
		t.Fatalf("status %d body %s", code, body)
	}
}

func TestStreamJobLogsStreamsOnlyJobContainer(t *testing.T) {
	now := time.Now()
	other := sinkerPod("dd-orders-status", corev1.PodRunning, now, false, false)
	other.Namespace = "default"
	other.Labels = map[string]string{"data": "orders"}
	job := sinkerPod("dd-orders-abc", corev1.PodRunning, now.Add(-time.Minute), true, false)
	job.Namespace = "default"
	job.Labels = map[string]string{"data": "orders"}
	client := fake.NewSimpleClientset(&other, &job)

	body, code := performJobLogsLive(t, client, "default", "orders")
	if code != 200 {
		t.Fatalf("status %d body %s", code, body)
	}
	if !strings.Contains(body, "event: meta") || !strings.Contains(body, "data: dd-orders-abc") {
		t.Fatalf("missing pod meta: %s", body)
	}
	if !strings.Contains(body, "event: log") || !strings.Contains(body, "data: fake logs") {
		t.Fatalf("missing log event: %s", body)
	}
	if !strings.Contains(body, "event: end") {
		t.Fatalf("missing end event: %s", body)
	}

	var sawLog bool
	for _, action := range client.Actions() {
		if action.GetSubresource() != "log" {
			continue
		}
		sawLog = true
		generic, ok := action.(k8stesting.GenericAction)
		if !ok {
			t.Fatalf("log action type %T", action)
		}
		opts, ok := generic.GetValue().(*corev1.PodLogOptions)
		if !ok || opts == nil {
			t.Fatalf("log options %#v", generic.GetValue())
		}
		if opts.Container != dataSinkerJobContainer {
			t.Fatalf("container %q", opts.Container)
		}
		if !opts.Follow {
			t.Fatal("expected follow")
		}
	}
	if !sawLog {
		t.Fatal("GetLogs was not called")
	}
}

func performJobLogsLive(t *testing.T, client *fake.Clientset, namespace, name string) (string, int) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	addr := ln.Addr().String()
	ln.Close()

	h := NewDataDescriptorHandler(nil, slog.New(slog.DiscardHandler))
	h.SetKubernetes(client)
	engine := server.New(
		server.WithHostPorts(addr),
		server.WithDisablePrintRoute(true),
		server.WithSenseClientDisconnection(true),
	)
	engine.GET("/api/v1/namespaces/:namespace/descriptor-job-logs/:name", h.StreamJobLogs)
	go func() { _ = engine.Run() }()
	t.Cleanup(func() { _ = engine.Close() })
	waitUntil(t, engine.IsRunning)

	resp, err := http.Get("http://" + addr + "/api/v1/namespaces/" + namespace + "/descriptor-job-logs/" + name)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return string(body), resp.StatusCode
}

func waitUntil(t *testing.T, ready func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if ready() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("server did not start")
}

func performJobLogs(t *testing.T, client *fake.Clientset, namespace, name string) (string, int) {
	t.Helper()
	h := NewDataDescriptorHandler(nil, slog.New(slog.DiscardHandler))
	h.SetKubernetes(client)
	engine := server.New(server.WithDisablePrintRoute(true))
	engine.GET("/api/v1/namespaces/:namespace/descriptor-job-logs/:name", h.StreamJobLogs)
	w := ut.PerformRequest(engine.Engine, "GET", "/api/v1/namespaces/"+namespace+"/descriptor-job-logs/"+name, nil)
	return string(w.Body.Bytes()), w.Code
}

func sinkerPod(name string, phase corev1.PodPhase, created time.Time, withJob, deleting bool) corev1.Pod {
	containers := []corev1.Container{{Name: "data-services"}, {Name: "data-sinker-status"}}
	if withJob {
		containers = append(containers, corev1.Container{Name: dataSinkerJobContainer})
	}
	pod := corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:              name,
			CreationTimestamp: metav1.NewTime(created),
		},
		Spec: corev1.PodSpec{Containers: containers},
		Status: corev1.PodStatus{
			Phase: phase,
		},
	}
	if deleting {
		ts := metav1.NewTime(created)
		pod.DeletionTimestamp = &ts
	}
	return pod
}
