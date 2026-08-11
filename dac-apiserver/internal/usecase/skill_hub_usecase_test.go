package usecase_test

import (
	"bytes"
	"context"
	"io"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/usecase"
)

type stubSkillHubClient struct {
	namespaces []domain.SkillNamespace
	skills     map[string][]domain.SkillInfo
	uploaded   *domain.SkillInfo
	deleted    []string
	reloaded   bool
}

func (s *stubSkillHubClient) ListNamespaces(ctx context.Context) ([]domain.SkillNamespace, error) {
	return s.namespaces, nil
}

func (s *stubSkillHubClient) NamespaceExists(ctx context.Context, namespace string) (bool, error) {
	for _, ns := range s.namespaces {
		if ns.ID == namespace {
			return true, nil
		}
	}
	return false, nil
}

func (s *stubSkillHubClient) CreateNamespace(ctx context.Context, namespace string) (*domain.SkillNamespace, error) {
	ns := domain.SkillNamespace{ID: namespace, Visibility: "public"}
	s.namespaces = append(s.namespaces, ns)
	return &ns, nil
}

func (s *stubSkillHubClient) DeleteNamespace(ctx context.Context, namespace string) error {
	return nil
}

func (s *stubSkillHubClient) ListSkills(ctx context.Context, namespace string) ([]domain.SkillInfo, error) {
	return s.skills[namespace], nil
}

func (s *stubSkillHubClient) GetSkill(ctx context.Context, namespace, name, version string) (*domain.SkillDetail, error) {
	return &domain.SkillDetail{
		Name: name, Namespace: namespace, Version: version, Detail: "body", AllowedTools: []string{"glob"},
	}, nil
}

func (s *stubSkillHubClient) CreateSkill(ctx context.Context, namespace string, req domain.CreateSkillRequest) (*domain.SkillInfo, error) {
	s.uploaded = &domain.SkillInfo{
		Name:        req.Name,
		Namespace:   namespace,
		Description: req.Description,
		Version:     req.Version,
		Filename:    req.Name + "-" + req.Version + ".zip",
	}
	return s.uploaded, nil
}

func (s *stubSkillHubClient) UploadSkill(ctx context.Context, namespace, filename string, r io.Reader) (*domain.SkillInfo, error) {
	body, _ := io.ReadAll(r)
	s.uploaded = &domain.SkillInfo{
		Name:        "demo",
		Namespace:   namespace,
		Version:     "1.0.0",
		Filename:    filename,
		Description: string(body),
	}
	return s.uploaded, nil
}

func (s *stubSkillHubClient) DownloadSkill(ctx context.Context, namespace, name, version string) (*domain.SkillDownload, error) {
	return &domain.SkillDownload{
		Filename: name + ".zip",
		Version:  version,
		Body:     io.NopCloser(bytes.NewReader([]byte("zip"))),
		Size:     3,
	}, nil
}

func (s *stubSkillHubClient) DeleteSkill(ctx context.Context, namespace, name, version string) error {
	s.deleted = append(s.deleted, namespace+"/"+name+"@"+version)
	return nil
}

func (s *stubSkillHubClient) Reload(ctx context.Context) ([]domain.SkillInfo, error) {
	s.reloaded = true
	return s.skills["default"], nil
}

func TestSkillHubUsecase_ListSkillsRequiresNamespace(t *testing.T) {
	uc := usecase.NewSkillHubUsecase(&stubSkillHubClient{}, nil)
	_, err := uc.ListSkills(context.Background(), "  ")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want invalid input, got %v", err)
	}
}

func TestSkillHubUsecase_CreateNamespaceRequiresName(t *testing.T) {
	uc := usecase.NewSkillHubUsecase(&stubSkillHubClient{}, nil)
	_, err := uc.CreateNamespace(context.Background(), "")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want invalid input, got %v", err)
	}
}

func TestSkillHubUsecase_ListAndUpload(t *testing.T) {
	stub := &stubSkillHubClient{
		namespaces: []domain.SkillNamespace{{ID: "default", Visibility: "public"}},
		skills: map[string][]domain.SkillInfo{
			"default": {{Name: "hashgen", Namespace: "default", Version: "2.0.0"}},
		},
	}
	uc := usecase.NewSkillHubUsecase(stub, nil)

	items, err := uc.ListSkills(context.Background(), "default")
	if err != nil {
		t.Fatalf("ListSkills: %v", err)
	}
	if len(items) != 1 || items[0].Name != "hashgen" {
		t.Fatalf("unexpected items: %#v", items)
	}

	info, err := uc.UploadSkill(context.Background(), "default", "demo.zip", bytes.NewReader([]byte("payload")))
	if err != nil {
		t.Fatalf("UploadSkill: %v", err)
	}
	if info.Name != "demo" || stub.uploaded == nil || stub.uploaded.Description != "payload" {
		t.Fatalf("unexpected upload result: %#v stub=%#v", info, stub.uploaded)
	}
}

func TestSkillHubUsecase_DeleteAndReload(t *testing.T) {
	stub := &stubSkillHubClient{}
	uc := usecase.NewSkillHubUsecase(stub, nil)

	if err := uc.DeleteSkill(context.Background(), "default", "hashgen", "1.0.0"); err != nil {
		t.Fatalf("DeleteSkill: %v", err)
	}
	if len(stub.deleted) != 1 || stub.deleted[0] != "default/hashgen@1.0.0" {
		t.Fatalf("deleted=%v", stub.deleted)
	}

	if _, err := uc.Reload(context.Background()); err != nil {
		t.Fatalf("Reload: %v", err)
	}
	if !stub.reloaded {
		t.Fatal("expected reload to be called")
	}
}

func TestSkillHubUsecase_DownloadRequiresName(t *testing.T) {
	uc := usecase.NewSkillHubUsecase(&stubSkillHubClient{}, nil)
	_, err := uc.DownloadSkill(context.Background(), "default", " ", "")
	if !domain.IsInvalidInput(err) {
		t.Fatalf("want invalid input, got %v", err)
	}
}

func TestSkillHubUsecase_NamespaceExists(t *testing.T) {
	stub := &stubSkillHubClient{
		namespaces: []domain.SkillNamespace{{ID: "team-a"}},
	}
	uc := usecase.NewSkillHubUsecase(stub, nil)
	ok, err := uc.NamespaceExists(context.Background(), "team-a")
	if err != nil || !ok {
		t.Fatalf("exists=%v err=%v", ok, err)
	}
	ok, err = uc.NamespaceExists(context.Background(), "missing")
	if err != nil || ok {
		t.Fatalf("exists=%v err=%v", ok, err)
	}
}
