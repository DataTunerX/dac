package usecase

import (
	"context"
	"testing"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type mockSystemConfigRepo struct {
	store map[string]*domain.RawSystemConfigMap
}

func (m *mockSystemConfigRepo) Get(_ context.Context, name string) (*domain.RawSystemConfigMap, error) {
	if cm, ok := m.store[name]; ok {
		copy := *cm
		return &copy, nil
	}
	return nil, domain.NewNotFoundError("SystemConfiguration", name)
}

func (m *mockSystemConfigRepo) ListArchives(_ context.Context, sourceName string) ([]*domain.RawSystemConfigMap, error) {
	var out []*domain.RawSystemConfigMap
	for _, cm := range m.store {
		if cm.Labels != nil &&
			cm.Labels[domain.SystemConfigArchiveLabel] == "true" &&
			cm.Labels[domain.SystemConfigSourceLabel] == sourceName {
			out = append(out, cm)
		}
	}
	return out, nil
}

func (m *mockSystemConfigRepo) Create(_ context.Context, cm *domain.RawSystemConfigMap) (*domain.RawSystemConfigMap, error) {
	if _, exists := m.store[cm.Name]; exists {
		return nil, domain.NewAlreadyExistsError("SystemConfiguration", cm.Name)
	}
	copy := *cm
	copy.ResourceVersion = "rv-" + cm.Name
	m.store[cm.Name] = &copy
	return &copy, nil
}

func (m *mockSystemConfigRepo) Replace(_ context.Context, cm *domain.RawSystemConfigMap) (*domain.RawSystemConfigMap, error) {
	existing, ok := m.store[cm.Name]
	if !ok {
		return nil, domain.NewNotFoundError("SystemConfiguration", cm.Name)
	}
	if cm.ResourceVersion != "" && existing.ResourceVersion != cm.ResourceVersion {
		return nil, domain.NewConflictError("resource version mismatch")
	}
	existing.Data = cloneStringMap(cm.Data)
	existing.Labels = cloneStringMap(cm.Labels)
	existing.ResourceVersion = existing.ResourceVersion + "-next"
	copy := *existing
	return &copy, nil
}

func (m *mockSystemConfigRepo) Delete(_ context.Context, name, resourceVersion string) error {
	cm, ok := m.store[name]
	if !ok {
		return domain.NewNotFoundError("SystemConfiguration", name)
	}
	if resourceVersion != "" && cm.ResourceVersion != resourceVersion {
		return domain.NewConflictError("resource version mismatch")
	}
	delete(m.store, name)
	return nil
}

func TestSystemConfigUpdate_ArchivesAndPreservesHiddenKeys(t *testing.T) {
	repo := &mockSystemConfigRepo{
		store: map[string]*domain.RawSystemConfigMap{
			string(domain.SystemConfigDAC): {
				Name:            string(domain.SystemConfigDAC),
				Namespace:       domain.SystemConfigNamespace,
				ResourceVersion: "rv-1",
				Labels:          map[string]string{"app": "dac"},
				Data: map[string]string{
					"redis-host":               "redis.dac.svc",
					"orchestrator-agent-image": "img:v1",
					"default-planner-llm":      "llm-old",
				},
				CreationTimestamp: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC),
			},
		},
	}

	uc := NewSystemConfigUsecase(repo, nil).(*systemConfigUsecase)
	fixed := time.Date(2026, 5, 18, 12, 0, 0, 123456789, time.UTC)
	uc.now = func() time.Time { return fixed }

	updated, err := uc.Update(context.Background(), domain.SystemConfigDAC, &domain.UpdateSystemConfigurationRequest{
		ResourceVersion: "rv-1",
		Data: map[string]string{
			"orchestrator-agent-image": "img:v2",
			"default-planner-llm":      "llm-new",
		},
	})
	if err != nil {
		t.Fatalf("Update() error = %v", err)
	}
	if updated.ResourceVersion == "" {
		t.Fatal("expected new resourceVersion on active configuration")
	}
	if updated.Data["orchestrator-agent-image"] != "img:v2" {
		t.Fatalf("active image = %q, want img:v2", updated.Data["orchestrator-agent-image"])
	}

	active := repo.store[string(domain.SystemConfigDAC)]
	if active == nil {
		t.Fatal("active configuration must remain present during update")
	}
	if active.Data["redis-host"] != "redis.dac.svc" {
		t.Fatalf("hidden key lost on active CM: redis-host=%q", active.Data["redis-host"])
	}

	archiveVersion := newArchiveVersion(fixed)
	archiveName := string(domain.SystemConfigDAC) + "-" + archiveVersion
	archive, ok := repo.store[archiveName]
	if !ok {
		t.Fatalf("archive %q not created", archiveName)
	}
	if archive.Data["orchestrator-agent-image"] != "img:v1" {
		t.Fatalf("archive should keep previous image, got %q", archive.Data["orchestrator-agent-image"])
	}
}

func TestSystemConfigUpdate_ResourceVersionConflict(t *testing.T) {
	repo := &mockSystemConfigRepo{
		store: map[string]*domain.RawSystemConfigMap{
			string(domain.SystemConfigDAC): {
				Name:            string(domain.SystemConfigDAC),
				ResourceVersion: "rv-current",
				Data:            map[string]string{"orchestrator-agent-image": "img:v1"},
			},
		},
	}
	uc := NewSystemConfigUsecase(repo, nil)

	_, err := uc.Update(context.Background(), domain.SystemConfigDAC, &domain.UpdateSystemConfigurationRequest{
		ResourceVersion: "rv-stale",
		Data:            map[string]string{"orchestrator-agent-image": "img:v2"},
	})
	if err == nil || !domain.IsConflict(err) {
		t.Fatalf("expected conflict, got %v", err)
	}
}

func TestSystemConfigUpdate_RequiresResourceVersionWhenExists(t *testing.T) {
	repo := &mockSystemConfigRepo{
		store: map[string]*domain.RawSystemConfigMap{
			string(domain.SystemConfigDAC): {
				Name:            string(domain.SystemConfigDAC),
				ResourceVersion: "rv-1",
				Data:            map[string]string{},
			},
		},
	}
	uc := NewSystemConfigUsecase(repo, nil)

	_, err := uc.Update(context.Background(), domain.SystemConfigDAC, &domain.UpdateSystemConfigurationRequest{
		Data: map[string]string{"orchestrator-agent-image": "img:v2"},
	})
	if err == nil || !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid input, got %v", err)
	}
}

type replaceFailRepo struct {
	mockSystemConfigRepo
	replaceFails bool
}

func (m *replaceFailRepo) Replace(ctx context.Context, cm *domain.RawSystemConfigMap) (*domain.RawSystemConfigMap, error) {
	if m.replaceFails {
		return nil, domain.NewInternalError(context.DeadlineExceeded)
	}
	return m.mockSystemConfigRepo.Replace(ctx, cm)
}

func TestSystemConfigUpdate_ActiveUnchangedWhenReplaceFails(t *testing.T) {
	base := &domain.RawSystemConfigMap{
		Name:            string(domain.SystemConfigDAC),
		Namespace:       domain.SystemConfigNamespace,
		ResourceVersion: "rv-1",
		Data: map[string]string{
			"redis-host":               "redis.dac.svc",
			"orchestrator-agent-image": "img:v1",
		},
	}
	repo := &replaceFailRepo{
		mockSystemConfigRepo: mockSystemConfigRepo{
			store: map[string]*domain.RawSystemConfigMap{
				string(domain.SystemConfigDAC): base,
			},
		},
		replaceFails: true,
	}
	uc := NewSystemConfigUsecase(repo, nil).(*systemConfigUsecase)
	uc.now = func() time.Time { return time.Date(2026, 5, 18, 12, 0, 0, 0, time.UTC) }

	_, err := uc.Update(context.Background(), domain.SystemConfigDAC, &domain.UpdateSystemConfigurationRequest{
		ResourceVersion: "rv-1",
		Data:            map[string]string{"orchestrator-agent-image": "img:v2"},
	})
	if err == nil {
		t.Fatal("expected replace failure")
	}

	active := repo.store[string(domain.SystemConfigDAC)]
	if active == nil {
		t.Fatal("active configuration must not be deleted on failed update")
	}
	if active.Data["orchestrator-agent-image"] != "img:v1" {
		t.Fatalf("active image = %q, want img:v1 (unchanged)", active.Data["orchestrator-agent-image"])
	}

	archiveVersion := newArchiveVersion(uc.now())
	archiveName := string(domain.SystemConfigDAC) + "-" + archiveVersion
	if _, ok := repo.store[archiveName]; ok {
		t.Fatalf("orphan archive %q should be removed after failed replace", archiveName)
	}
}

func TestValidateExposedUpdate_RejectsUnknownKeys(t *testing.T) {
	err := validateExposedUpdate(map[string]string{"redis-host": "x"}, domain.DACConfigurationExposedKeys)
	if err == nil || !domain.IsInvalidInput(err) {
		t.Fatalf("expected invalid input, got %v", err)
	}
}

func TestSystemConfigGet_NotFoundReturnsExistsFalse(t *testing.T) {
	uc := NewSystemConfigUsecase(&mockSystemConfigRepo{store: map[string]*domain.RawSystemConfigMap{}}, nil)
	cfg, err := uc.Get(context.Background(), domain.SystemConfigDAC)
	if err != nil {
		t.Fatalf("Get() error = %v", err)
	}
	if cfg.Exists {
		t.Fatal("expected exists=false")
	}
}
