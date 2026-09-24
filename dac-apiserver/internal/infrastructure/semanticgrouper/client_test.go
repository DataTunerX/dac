package semanticgrouper

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

func TestRefreshGroupPostsModeAndDescriptor(t *testing.T) {
	t.Parallel()

	var gotPath string
	var gotBody map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		raw, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(raw, &gotBody); err != nil {
			t.Errorf("unmarshal body: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"task_id":"task-1"}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, time.Second, nil)
	taskID, err := c.RefreshGroup(
		context.Background(),
		"group-1",
		domain.SemanticGroupRefreshIncremental,
		&domain.SemanticGroupRefreshDescriptor{Namespace: "ns", Name: "orders"},
	)
	if err != nil {
		t.Fatalf("RefreshGroup() error = %v", err)
	}
	if taskID != "task-1" {
		t.Fatalf("task id = %q, want task-1", taskID)
	}
	if gotPath != "/api/v1/group/refresh" {
		t.Fatalf("path = %q, want /api/v1/group/refresh", gotPath)
	}
	if gotBody["group_id"] != "group-1" {
		t.Fatalf("group_id = %#v", gotBody["group_id"])
	}
	if gotBody["mode"] != domain.SemanticGroupRefreshIncremental {
		t.Fatalf("mode = %#v", gotBody["mode"])
	}
	desc, _ := gotBody["descriptor"].(map[string]any)
	if desc["namespace"] != "ns" || desc["name"] != "orders" {
		t.Fatalf("descriptor = %#v", gotBody["descriptor"])
	}
}
