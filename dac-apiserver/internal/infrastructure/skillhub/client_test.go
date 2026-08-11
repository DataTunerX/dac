package skillhub

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

func TestClient_ListNamespaces(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/namespaces" {
			t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"count":2,"namespaces":[{"id":"default","visibility":"public"},{"id":"team-a","visibility":"public"}]}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	items, err := c.ListNamespaces(context.Background())
	if err != nil {
		t.Fatalf("ListNamespaces: %v", err)
	}
	if len(items) != 2 || items[0].ID != "default" || items[1].ID != "team-a" {
		t.Fatalf("unexpected items: %#v", items)
	}
}

func TestClient_ListSkills(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/namespaces/team-a/skills" {
			t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"count":1,
			"skills_dir":"/app/skills/team-a",
			"skills":[{
				"name":"report",
				"namespace":"team-a",
				"description":"demo",
				"version":"1.1.0",
				"filename":"report-1.1.0.zip",
				"download_url":"/namespaces/team-a/skills/report.zip",
				"available_versions":["1.1.0","1.0.0"]
			}]
		}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	items, err := c.ListSkills(context.Background(), "team-a")
	if err != nil {
		t.Fatalf("ListSkills: %v", err)
	}
	if len(items) != 1 {
		t.Fatalf("want 1 skill, got %d", len(items))
	}
	if items[0].Name != "report" || items[0].Version != "1.1.0" || len(items[0].AvailableVersions) != 2 {
		t.Fatalf("unexpected skill: %#v", items[0])
	}
}

func TestClient_CreateNamespaceConflict(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/namespaces/team-a" {
			t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"error":"namespace already exists","status_code":409}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	_, err := c.CreateNamespace(context.Background(), "team-a")
	if err == nil {
		t.Fatal("expected conflict/already-exists error")
	}
	if !domain.IsAlreadyExists(err) {
		t.Fatalf("want AlreadyExists, got %v", err)
	}
}

func TestClient_DeleteNamespaceNonEmpty(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusConflict)
		_, _ = w.Write([]byte(`{"error":"namespace is not empty","status_code":409}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	err := c.DeleteNamespace(context.Background(), "team-a")
	if !domain.IsConflict(err) {
		t.Fatalf("want Conflict, got %v", err)
	}
}

func TestClient_CreateSkill(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/namespaces/team-a/skills/create" {
			t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		if r.Header.Get("Content-Type") != "application/json" {
			t.Fatalf("want json content-type, got %q", r.Header.Get("Content-Type"))
		}
		body, _ := io.ReadAll(r.Body)
		if !strings.Contains(string(body), `"name":"form-skill"`) {
			t.Fatalf("body=%s", body)
		}
		if !strings.Contains(string(body), `"allowed_tools"`) {
			t.Fatalf("expected allowed_tools in body=%s", body)
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{
			"name":"form-skill",
			"namespace":"team-a",
			"description":"from form",
			"version":"1.0.0",
			"filename":"form-skill-1.0.0.zip",
			"available_versions":["1.0.0"]
		}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	info, err := c.CreateSkill(context.Background(), "team-a", domain.CreateSkillRequest{
		Name:         "form-skill",
		Description:  "from form",
		Detail:       "## Hi\n",
		Version:      "1.0.0",
		AllowedTools: []string{"glob"},
	})
	if err != nil {
		t.Fatalf("CreateSkill: %v", err)
	}
	if info.Name != "form-skill" || info.Namespace != "team-a" {
		t.Fatalf("unexpected info: %#v", info)
	}
}

func TestClient_UpdateSkill(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/namespaces/team-a/skills/form-skill/update" {
			t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		if r.URL.Query().Get("version") != "1.0.0" {
			t.Fatalf("want source version query, got %q", r.URL.RawQuery)
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{
			"name":"form-skill",
			"namespace":"team-a",
			"description":"updated",
			"version":"1.1.0",
			"filename":"form-skill-1.1.0.zip",
			"available_versions":["1.0.0","1.1.0"]
		}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	info, err := c.UpdateSkill(context.Background(), "team-a", "form-skill", "1.0.0", domain.CreateSkillRequest{
		Name:         "form-skill",
		Description:  "updated",
		Detail:       "## Hi\n",
		Version:      "1.1.0",
		AllowedTools: []string{"grep"},
	})
	if err != nil {
		t.Fatalf("UpdateSkill: %v", err)
	}
	if info.Version != "1.1.0" || info.Description != "updated" {
		t.Fatalf("unexpected info: %#v", info)
	}
}

func TestClient_UploadSkill(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/namespaces/default/skills" {
			t.Fatalf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data") {
			t.Fatalf("want multipart content-type, got %q", r.Header.Get("Content-Type"))
		}
		if err := r.ParseMultipartForm(4 << 20); err != nil {
			t.Fatalf("ParseMultipartForm: %v", err)
		}
		file, header, err := r.FormFile("file")
		if err != nil {
			t.Fatalf("FormFile: %v", err)
		}
		defer file.Close()
		if header.Filename != "demo.zip" {
			t.Fatalf("filename=%q", header.Filename)
		}
		body, _ := io.ReadAll(file)
		if string(body) != "zip-bytes" {
			t.Fatalf("body=%q", body)
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{
			"name":"demo",
			"namespace":"default",
			"description":"d",
			"version":"1.0.0",
			"filename":"demo-1.0.0.zip",
			"available_versions":["1.0.0"]
		}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	info, err := c.UploadSkill(context.Background(), "default", "demo.zip", bytes.NewReader([]byte("zip-bytes")))
	if err != nil {
		t.Fatalf("UploadSkill: %v", err)
	}
	if info.Name != "demo" || info.Version != "1.0.0" {
		t.Fatalf("unexpected info: %#v", info)
	}
}

func TestClient_DownloadSkill(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/namespaces/default/skills/hashgen.zip" {
			t.Fatalf("path=%s", r.URL.Path)
		}
		if r.URL.Query().Get("version") != "2.0.0" {
			t.Fatalf("version=%q", r.URL.Query().Get("version"))
		}
		w.Header().Set("Content-Type", "application/zip")
		w.Header().Set("Content-Disposition", `attachment; filename="hashgen.zip"`)
		w.Header().Set("X-Skill-Version", "2.0.0")
		_, _ = w.Write([]byte("PK\x03\x04fake"))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	dl, err := c.DownloadSkill(context.Background(), "default", "hashgen", "2.0.0")
	if err != nil {
		t.Fatalf("DownloadSkill: %v", err)
	}
	defer dl.Body.Close()
	if dl.Version != "2.0.0" || dl.Filename != "hashgen.zip" {
		t.Fatalf("unexpected meta: %#v", dl)
	}
	body, err := io.ReadAll(dl.Body)
	if err != nil {
		t.Fatalf("read body: %v", err)
	}
	if string(body) != "PK\x03\x04fake" {
		t.Fatalf("body=%q", body)
	}
}

func TestClient_DeleteSkill(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodDelete {
			t.Fatalf("method=%s", r.Method)
		}
		if r.URL.Path != "/namespaces/default/skills/hashgen.zip" {
			t.Fatalf("path=%s", r.URL.Path)
		}
		if r.URL.Query().Get("version") != "1.0.0" {
			t.Fatalf("version=%q", r.URL.Query().Get("version"))
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	if err := c.DeleteSkill(context.Background(), "default", "hashgen", "1.0.0"); err != nil {
		t.Fatalf("DeleteSkill: %v", err)
	}
}

func TestClient_Reload(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/skills/reload" {
			t.Fatalf("unexpected %s %s", r.Method, r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"count":0,"skills":[]}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	items, err := c.Reload(context.Background())
	if err != nil {
		t.Fatalf("Reload: %v", err)
	}
	if len(items) != 0 {
		t.Fatalf("want empty, got %#v", items)
	}
}

func TestClient_NotFoundMapped(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = w.Write([]byte(`{"error":"skill not found","status_code":404}`))
	}))
	defer srv.Close()

	c := NewClient(srv.URL, 0, nil)
	err := c.DeleteSkill(context.Background(), "default", "missing", "")
	if !domain.IsNotFound(err) {
		t.Fatalf("want NotFound, got %v", err)
	}
}

func TestClient_EmptyBaseURL(t *testing.T) {
	c := NewClient("  ", 0, nil)
	_, err := c.ListNamespaces(context.Background())
	if err == nil {
		t.Fatal("expected error for empty base URL")
	}
}

func TestClient_Validation(t *testing.T) {
	c := NewClient("http://example.invalid", 0, nil)
	if _, err := c.ListSkills(context.Background(), "  "); !domain.IsInvalidInput(err) {
		t.Fatalf("ListSkills empty ns: %v", err)
	}
	if _, err := c.UploadSkill(context.Background(), "default", "", bytes.NewReader(nil)); !domain.IsInvalidInput(err) {
		t.Fatalf("UploadSkill empty filename: %v", err)
	}
	if _, err := c.DownloadSkill(context.Background(), "default", "", ""); !domain.IsInvalidInput(err) {
		t.Fatalf("DownloadSkill empty name: %v", err)
	}
}

func TestMapHTTPError(t *testing.T) {
	cases := []struct {
		status int
		body   string
		check  func(error) bool
	}{
		{400, `{"error":"bad ns","status_code":400}`, domain.IsInvalidInput},
		{404, `{"error":"missing","status_code":404}`, domain.IsNotFound},
		{409, `{"error":"namespace already exists","status_code":409}`, domain.IsAlreadyExists},
		{409, `{"error":"namespace is not empty","status_code":409}`, domain.IsConflict},
		{500, `{"error":"boom","status_code":500}`, domain.IsInternalError},
	}
	for _, tc := range cases {
		err := mapHTTPError(tc.status, []byte(tc.body))
		if !tc.check(err) {
			t.Fatalf("status %d: unexpected err %v", tc.status, err)
		}
	}
	if err := mapHTTPError(200, nil); err != nil {
		t.Fatalf("200 should be nil, got %v", err)
	}
}
