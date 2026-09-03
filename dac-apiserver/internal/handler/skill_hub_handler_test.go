package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"testing"

	"github.com/cloudwego/hertz/pkg/app"
	"github.com/cloudwego/hertz/pkg/common/ut"
	"github.com/cloudwego/hertz/pkg/route/param"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type stubSkillHubUC struct {
	namespaces []domain.SkillNamespace
	skills     []domain.SkillInfo
	uploadErr  error
	deleteErr  error
	uploaded   bool
	deleted    string
}

func (s *stubSkillHubUC) ListNamespaces(ctx context.Context) ([]domain.SkillNamespace, error) {
	return s.namespaces, nil
}
func (s *stubSkillHubUC) NamespaceExists(ctx context.Context, namespace string) (bool, error) {
	return false, nil
}
func (s *stubSkillHubUC) CreateNamespace(ctx context.Context, namespace string) (*domain.SkillNamespace, error) {
	return &domain.SkillNamespace{ID: namespace, Visibility: "public"}, nil
}
func (s *stubSkillHubUC) DeleteNamespace(ctx context.Context, namespace string) error {
	return nil
}
func (s *stubSkillHubUC) ListSkills(ctx context.Context, namespace string) ([]domain.SkillInfo, error) {
	return s.skills, nil
}
func (s *stubSkillHubUC) GetSkill(ctx context.Context, namespace, name, version string) (*domain.SkillDetail, error) {
	return &domain.SkillDetail{
		Name: name, Namespace: namespace, Version: version, Detail: "body", AllowedTools: []string{"glob"},
	}, nil
}
func (s *stubSkillHubUC) CreateSkill(ctx context.Context, namespace string, req domain.CreateSkillRequest) (*domain.SkillInfo, error) {
	if s.uploadErr != nil {
		return nil, s.uploadErr
	}
	s.uploaded = true
	return &domain.SkillInfo{
		Name:        req.Name,
		Namespace:   namespace,
		Description: req.Description,
		Version:     req.Version,
		Filename:    req.Name + "-" + req.Version + ".zip",
	}, nil
}
func (s *stubSkillHubUC) UpdateSkill(ctx context.Context, namespace, name, sourceVersion string, req domain.CreateSkillRequest) (*domain.SkillInfo, error) {
	if s.uploadErr != nil {
		return nil, s.uploadErr
	}
	s.uploaded = true
	return &domain.SkillInfo{
		Name:        name,
		Namespace:   namespace,
		Description: req.Description,
		Version:     req.Version,
		Filename:    name + "-" + req.Version + ".zip",
	}, nil
}
func (s *stubSkillHubUC) UploadSkill(ctx context.Context, namespace, filename string, r io.Reader) (*domain.SkillInfo, error) {
	if s.uploadErr != nil {
		return nil, s.uploadErr
	}
	s.uploaded = true
	_, _ = io.ReadAll(r)
	return &domain.SkillInfo{Name: "demo", Namespace: namespace, Version: "1.0.0", Filename: filename}, nil
}
func (s *stubSkillHubUC) DownloadSkill(ctx context.Context, namespace, name, version string) (*domain.SkillDownload, error) {
	return &domain.SkillDownload{
		Filename: name + ".zip",
		Version:  "1.0.0",
		Body:     io.NopCloser(bytes.NewReader([]byte("PKZIP"))),
		Size:     5,
	}, nil
}
func (s *stubSkillHubUC) DeleteSkill(ctx context.Context, namespace, name, version string) error {
	if s.deleteErr != nil {
		return s.deleteErr
	}
	s.deleted = namespace + "/" + name + "@" + version
	return nil
}
func (s *stubSkillHubUC) Reload(ctx context.Context) ([]domain.SkillInfo, error) {
	return s.skills, nil
}

func newSkillHubTestHandler(uc domain.SkillHubUsecase) *SkillHubHandler {
	return NewSkillHubHandler(uc, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

func TestSkillHubHandler_ListNamespaces(t *testing.T) {
	uc := &stubSkillHubUC{
		namespaces: []domain.SkillNamespace{{ID: "team-a", Visibility: "public"}},
	}
	h := newSkillHubTestHandler(uc)
	c := app.NewContext(0)

	h.ListNamespaces(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d", c.Response.StatusCode())
	}
	var body Response
	if err := json.Unmarshal(c.Response.Body(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Code != "SUCCESS" {
		t.Fatalf("code=%s", body.Code)
	}
	data, ok := body.Data.(map[string]any)
	if !ok {
		t.Fatalf("data type %T", body.Data)
	}
	if int(data["totalCount"].(float64)) != 1 {
		t.Fatalf("totalCount=%v", data["totalCount"])
	}
}

func TestSkillHubHandler_ListSkills(t *testing.T) {
	uc := &stubSkillHubUC{
		skills: []domain.SkillInfo{{Name: "hashgen", Namespace: "default", Version: "2.0.0"}},
	}
	h := newSkillHubTestHandler(uc)
	c := app.NewContext(0)
	c.Params = append(c.Params, param.Param{Key: "ns", Value: "default"})

	h.ListSkills(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	var body Response
	if err := json.Unmarshal(c.Response.Body(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	data := body.Data.(map[string]any)
	items := data["items"].([]any)
	if len(items) != 1 {
		t.Fatalf("items=%v", items)
	}
}

func TestSkillHubHandler_CreateNamespaceRequiresName(t *testing.T) {
	h := newSkillHubTestHandler(&stubSkillHubUC{})
	body := `{"name":""}`
	c := ut.CreateUtRequestContext(
		http.MethodPost,
		"/api/v1/skills/namespaces",
		&ut.Body{Body: bytes.NewBufferString(body), Len: len(body)},
		ut.Header{Key: "Content-Type", Value: "application/json"},
	)

	h.CreateNamespace(context.Background(), c)

	if c.Response.StatusCode() != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestSkillHubHandler_CreateNamespace(t *testing.T) {
	h := newSkillHubTestHandler(&stubSkillHubUC{})
	body := `{"name":"team-a"}`
	c := ut.CreateUtRequestContext(
		http.MethodPost,
		"/api/v1/skills/namespaces",
		&ut.Body{Body: bytes.NewBufferString(body), Len: len(body)},
		ut.Header{Key: "Content-Type", Value: "application/json"},
	)

	h.CreateNamespace(context.Background(), c)

	if c.Response.StatusCode() != http.StatusCreated {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestSkillHubHandler_CreateSkill(t *testing.T) {
	uc := &stubSkillHubUC{}
	h := newSkillHubTestHandler(uc)

	body := `{"name":"form-skill","description":"from form","detail":"## Hi\n","version":"1.0.0","allowedTools":["glob"]}`
	c := ut.CreateUtRequestContext(
		"POST",
		"/skills/namespaces/team-a/skills/create",
		&ut.Body{Body: bytes.NewBufferString(body), Len: len(body)},
		ut.Header{Key: "Content-Type", Value: "application/json"},
	)
	c.Params = append(c.Params, param.Param{Key: "ns", Value: "team-a"})

	h.CreateSkill(context.Background(), c)

	if c.Response.StatusCode() != http.StatusCreated {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	if !uc.uploaded {
		t.Fatal("expected create to be called")
	}
}

func TestSkillHubHandler_UploadSkill(t *testing.T) {
	uc := &stubSkillHubUC{}
	h := newSkillHubTestHandler(uc)

	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	part, err := w.CreateFormFile("file", "demo.zip")
	if err != nil {
		t.Fatal(err)
	}
	_, _ = part.Write([]byte("zip-content"))
	_ = w.Close()

	c := app.NewContext(0)
	c.Params = append(c.Params, param.Param{Key: "ns", Value: "team-a"})
	c.Request.SetBody(buf.Bytes())
	c.Request.Header.SetContentTypeBytes([]byte(w.FormDataContentType()))
	c.Request.Header.SetMethod("POST")

	h.UploadSkill(context.Background(), c)

	if c.Response.StatusCode() != http.StatusCreated {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	if !uc.uploaded {
		t.Fatal("expected upload to be called")
	}
}

func TestSkillHubHandler_UploadSkillRejectsNonZip(t *testing.T) {
	h := newSkillHubTestHandler(&stubSkillHubUC{})

	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	part, _ := w.CreateFormFile("file", "demo.txt")
	_, _ = part.Write([]byte("nope"))
	_ = w.Close()

	c := app.NewContext(0)
	c.Params = append(c.Params, param.Param{Key: "ns", Value: "team-a"})
	c.Request.SetBody(buf.Bytes())
	c.Request.Header.SetContentTypeBytes([]byte(w.FormDataContentType()))

	h.UploadSkill(context.Background(), c)

	if c.Response.StatusCode() != http.StatusBadRequest {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestSkillHubHandler_DeleteSkill(t *testing.T) {
	uc := &stubSkillHubUC{}
	h := newSkillHubTestHandler(uc)
	c := app.NewContext(0)
	c.Params = append(c.Params,
		param.Param{Key: "ns", Value: "team-a"},
		param.Param{Key: "name", Value: "hashgen"},
	)
	c.Request.SetQueryString("version=1.0.0")

	h.DeleteSkill(context.Background(), c)

	if c.Response.StatusCode() != http.StatusNoContent {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	if uc.deleted != "team-a/hashgen@1.0.0" {
		t.Fatalf("deleted=%q", uc.deleted)
	}
}

func TestSkillHubHandler_DeleteSkillNotFound(t *testing.T) {
	uc := &stubSkillHubUC{deleteErr: domain.NewNotFoundError("skill", "missing")}
	h := newSkillHubTestHandler(uc)
	c := app.NewContext(0)
	c.Params = append(c.Params,
		param.Param{Key: "ns", Value: "team-a"},
		param.Param{Key: "name", Value: "missing"},
	)

	h.DeleteSkill(context.Background(), c)

	if c.Response.StatusCode() != http.StatusNotFound {
		t.Fatalf("status=%d", c.Response.StatusCode())
	}
}

func TestSkillHubHandler_DownloadSkill(t *testing.T) {
	h := newSkillHubTestHandler(&stubSkillHubUC{})
	c := app.NewContext(0)
	c.Params = append(c.Params,
		param.Param{Key: "ns", Value: "default"},
		param.Param{Key: "name", Value: "hashgen"},
	)

	h.DownloadSkill(context.Background(), c)

	if ct := string(c.Response.Header.ContentType()); ct != "application/zip" {
		t.Fatalf("content-type=%q", ct)
	}
	if got := string(c.Response.Header.Peek("X-Skill-Version")); got != "1.0.0" {
		t.Fatalf("X-Skill-Version=%q", got)
	}
}
