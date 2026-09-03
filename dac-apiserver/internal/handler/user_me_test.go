package handler

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"testing"
	"time"

	"github.com/cloudwego/hertz/pkg/app"

	"github.com/lvyanru/dac-apiserver/internal/config"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
	rbacengine "github.com/lvyanru/dac-apiserver/pkg/rbac"
)

// newMeTestContext builds a fresh RequestContext with the authenticated user set.
func newMeTestContext(userID string) *app.RequestContext {
	c := app.NewContext(0)
	if userID != "" {
		c.Set("user_id", userID)
	}
	return c
}

// fakeUserUsecase is a minimal stub of domain.UserUsecase for GetUser.
type fakeUserUsecase struct {
	users map[string]*entity.User
}

func (f *fakeUserUsecase) GetUser(_ context.Context, userID string) (*entity.User, error) {
	u, ok := f.users[userID]
	if !ok {
		return nil, domain.ErrNotFound
	}
	return u, nil
}

func (f *fakeUserUsecase) Login(_ context.Context, _, _ string) (*entity.User, error) {
	panic("unexpected Login")
}
func (f *fakeUserUsecase) Register(_ context.Context, _, _ string, _ *string) (*entity.User, error) {
	panic("unexpected Register")
}
func (f *fakeUserUsecase) ListUsers(_ context.Context, _, _ int) ([]*entity.User, int, error) {
	panic("unexpected ListUsers")
}
func (f *fakeUserUsecase) DeleteUser(_ context.Context, _ string) error {
	panic("unexpected DeleteUser")
}
func (f *fakeUserUsecase) UpdateUser(_ context.Context, _ string, _, _ *string) (*entity.User, error) {
	panic("unexpected UpdateUser")
}
func (f *fakeUserUsecase) SeedAdmin(_ context.Context) error {
	panic("unexpected SeedAdmin")
}

// fakeRBACStorage is a minimal rbac.Storage backing the engine for /users/me.
type fakeRBACStorage struct {
	platformRoles map[string][]rbacengine.PlatformRole
	tenantRoles   map[string][]rbacengine.TenantRole
	permCodes     map[string][]string // roleID → []permission code
}

func (s *fakeRBACStorage) GetUserPlatformRoles(_ context.Context, userID string) ([]rbacengine.PlatformRole, error) {
	roles, ok := s.platformRoles[userID]
	if !ok {
		return nil, nil
	}
	return roles, nil
}

func (s *fakeRBACStorage) GetTenantRole(_ context.Context, userID, tenantID string) (*rbacengine.TenantRole, error) {
	roles, ok := s.tenantRoles[userID]
	if !ok {
		return nil, nil
	}
	for _, r := range roles {
		if r.TenantID == tenantID {
			return &r, nil
		}
	}
	return nil, nil
}

func (s *fakeRBACStorage) ListTenantRolesByUser(_ context.Context, userID string) ([]rbacengine.TenantRole, error) {
	return s.tenantRoles[userID], nil
}

func (s *fakeRBACStorage) GetRolePermissions(_ context.Context, roleID string) ([]string, error) {
	ids, ok := s.permCodes[roleID]
	if !ok {
		return nil, nil
	}
	return ids, nil
}

func (s *fakeRBACStorage) GetTenantNamespaces(_ context.Context, _ string) ([]string, error) {
	return []string{"*"}, nil
}

func (s *fakeRBACStorage) IsTenantActive(_ context.Context, _ string) (bool, error) {
	return true, nil
}

func (s *fakeRBACStorage) PermissionsByCode(_ context.Context, code string) ([]rbacengine.Permission, error) {
	return []rbacengine.Permission{{ID: code, Code: code}}, nil
}

func (s *fakeRBACStorage) PermissionCodesByIDs(_ context.Context, ids []string) ([]string, error) {
	return ids, nil
}

func (s *fakeRBACStorage) TimeNow() time.Time { return time.Now() }

func newMeHandler(uc domain.UserUsecase, store *fakeRBACStorage) *UserHandler {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	h := NewUserHandler(uc, config.JWTConfig{
		Secret:     "test-secret-that-is-long-enough",
		Timeout:    15 * time.Minute,
		MaxRefresh: 7 * 24 * time.Hour,
	}, logger)
	if store != nil {
		engine := rbacengine.NewEngine(store, logger)
		h.WithRBACEngine(engine)
	}
	return h
}

func decodeMeResponse(t *testing.T, body []byte) dto.MeResponse {
	t.Helper()
	var envelope struct {
		Code    string          `json:"code"`
		Message string          `json:"message"`
		Data    json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("decode envelope: %v (body=%s)", err, body)
	}
	var me dto.MeResponse
	if err := json.Unmarshal(envelope.Data, &me); err != nil {
		t.Fatalf("decode MeResponse: %v (data=%s)", err, envelope.Data)
	}
	return me
}

// decodeUserResponse decodes the flat *UserResponse returned when RBAC engine is nil.
func decodeUserResponse(t *testing.T, body []byte) dto.UserResponse {
	t.Helper()
	var envelope struct {
		Code    string          `json:"code"`
		Message string          `json:"message"`
		Data    json.RawMessage `json:"data"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		t.Fatalf("decode envelope: %v (body=%s)", err, body)
	}
	var u dto.UserResponse
	if err := json.Unmarshal(envelope.Data, &u); err != nil {
		t.Fatalf("decode UserResponse: %v (data=%s)", err, envelope.Data)
	}
	return u
}

func TestGetCurrentUserWithoutRBACEngine(t *testing.T) {
	uc := &fakeUserUsecase{
		users: map[string]*entity.User{
			"u1": {ID: "u1", Username: "alice", CreatedAt: time.Unix(1_700_000_000, 0)},
		},
	}
	h := newMeHandler(uc, nil)
	c := newMeTestContext("u1")

	h.GetCurrentUser(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	// When RBAC engine is nil, the handler returns a flat *UserResponse, not a MeResponse
	user := decodeUserResponse(t, c.Response.Body())
	if user.Username != "alice" {
		t.Fatalf("username=%q, want alice", user.Username)
	}
}

func TestGetCurrentUserReturnsUnauthorizedWhenNoUserID(t *testing.T) {
	uc := &fakeUserUsecase{users: map[string]*entity.User{}}
	h := newMeHandler(uc, nil)
	c := newMeTestContext("") // no user_id

	h.GetCurrentUser(context.Background(), c)

	if c.Response.StatusCode() != http.StatusUnauthorized {
		t.Fatalf("status=%d body=%s, want 401", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestGetCurrentUserReturnsNotFoundForUnknownUser(t *testing.T) {
	uc := &fakeUserUsecase{users: map[string]*entity.User{}}
	h := newMeHandler(uc, nil)
	c := newMeTestContext("ghost")

	h.GetCurrentUser(context.Background(), c)

	if c.Response.StatusCode() != http.StatusNotFound {
		t.Fatalf("status=%d body=%s, want 404", c.Response.StatusCode(), c.Response.Body())
	}
}

func TestGetCurrentUserSuperAdminEnrichment(t *testing.T) {
	uc := &fakeUserUsecase{
		users: map[string]*entity.User{
			"u1": {ID: "u1", Username: "admin", CreatedAt: time.Unix(1_700_000_000, 0)},
		},
	}
	store := &fakeRBACStorage{
		platformRoles: map[string][]rbacengine.PlatformRole{
			"u1": {{ID: "super", Code: "super_admin", IsSuper: true}},
		},
		permCodes: map[string][]string{
			"super": {"tenant:manage", "platform:role:manage"},
		},
	}
	h := newMeHandler(uc, store)
	c := newMeTestContext("u1")

	h.GetCurrentUser(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	me := decodeMeResponse(t, c.Response.Body())
	if !me.IsSuper {
		t.Fatal("expected isSuper=true")
	}
	if len(me.PlatformRoles) != 1 || me.PlatformRoles[0] != "super_admin" {
		t.Fatalf("platformRoles=%v", me.PlatformRoles)
	}
	// Super admin permission codes are returned empty (implicit access)
	if len(me.PermissionCodes) != 0 {
		t.Fatalf("super admin permission codes should be empty, got %v", me.PermissionCodes)
	}
}

func TestGetCurrentUserNonSuperPlatformRoleEnrichment(t *testing.T) {
	uc := &fakeUserUsecase{
		users: map[string]*entity.User{
			"u1": {ID: "u1", Username: "ops", CreatedAt: time.Unix(1_700_000_000, 0)},
		},
	}
	store := &fakeRBACStorage{
		platformRoles: map[string][]rbacengine.PlatformRole{
			"u1": {{ID: "ops-id", Code: "ops", IsSuper: false}},
		},
		permCodes: map[string][]string{
			"ops-id": {"tenant:manage"},
		},
	}
	h := newMeHandler(uc, store)
	c := newMeTestContext("u1")

	h.GetCurrentUser(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	me := decodeMeResponse(t, c.Response.Body())
	if me.IsSuper {
		t.Fatal("expected isSuper=false")
	}
	if len(me.PlatformRoles) != 1 || me.PlatformRoles[0] != "ops" {
		t.Fatalf("platformRoles=%v", me.PlatformRoles)
	}
	if len(me.PermissionCodes) != 1 || me.PermissionCodes[0] != "tenant:manage" {
		t.Fatalf("permissionCodes=%v", me.PermissionCodes)
	}
}

func TestGetCurrentUserTenantRoleEnrichment(t *testing.T) {
	uc := &fakeUserUsecase{
		users: map[string]*entity.User{
			"u1": {ID: "u1", Username: "viewer", CreatedAt: time.Unix(1_700_000_000, 0)},
		},
	}
	store := &fakeRBACStorage{
		platformRoles: map[string][]rbacengine.PlatformRole{},
		tenantRoles: map[string][]rbacengine.TenantRole{
			"u1": {
				{ID: "tr1", Code: "viewer", TenantID: "t1"},
			},
		},
		permCodes: map[string][]string{
			"tr1": {"agent:read", "llmconfig:read"},
		},
	}
	h := newMeHandler(uc, store)
	c := newMeTestContext("u1")

	h.GetCurrentUser(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	me := decodeMeResponse(t, c.Response.Body())
	if me.IsSuper {
		t.Fatal("expected isSuper=false")
	}
	if len(me.PlatformRoles) != 0 {
		t.Fatalf("platformRoles=%v, expected empty", me.PlatformRoles)
	}
	if len(me.PermissionCodes) != 2 {
		t.Fatalf("permissionCodes=%v, expected 2 codes", me.PermissionCodes)
	}
}

func TestGetCurrentUserCombinedPlatformAndTenantCodes(t *testing.T) {
	uc := &fakeUserUsecase{
		users: map[string]*entity.User{
			"u1": {ID: "u1", Username: "hybrid", CreatedAt: time.Unix(1_700_000_000, 0)},
		},
	}
	store := &fakeRBACStorage{
		platformRoles: map[string][]rbacengine.PlatformRole{
			"u1": {{ID: "ops-id", Code: "ops", IsSuper: false}},
		},
		tenantRoles: map[string][]rbacengine.TenantRole{
			"u1": {
				{ID: "tr1", Code: "editor", TenantID: "t1"},
				{ID: "tr2", Code: "viewer", TenantID: "t2"},
			},
		},
		permCodes: map[string][]string{
			"ops-id": {"tenant:manage"},
			"tr1":    {"agent:create", "agent:update"},
			"tr2":    {"agent:read"},
		},
	}
	h := newMeHandler(uc, store)
	c := newMeTestContext("u1")

	h.GetCurrentUser(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	me := decodeMeResponse(t, c.Response.Body())
	if len(me.PlatformRoles) != 1 || me.PlatformRoles[0] != "ops" {
		t.Fatalf("platformRoles=%v", me.PlatformRoles)
	}
	// Combined: tenant:manage + agent:create + agent:update + agent:read = 4
	if len(me.PermissionCodes) != 4 {
		t.Fatalf("permissionCodes=%v, expected 4 codes", me.PermissionCodes)
	}
}

func TestGetCurrentUserNewUserEmptyPermissions(t *testing.T) {
	uc := &fakeUserUsecase{
		users: map[string]*entity.User{
			"u1": {ID: "u1", Username: "newbie", CreatedAt: time.Unix(1_700_000_000, 0)},
		},
	}
	store := &fakeRBACStorage{
		platformRoles: map[string][]rbacengine.PlatformRole{},
		tenantRoles:   map[string][]rbacengine.TenantRole{},
		permCodes:     map[string][]string{},
	}
	h := newMeHandler(uc, store)
	c := newMeTestContext("u1")

	h.GetCurrentUser(context.Background(), c)

	if c.Response.StatusCode() != http.StatusOK {
		t.Fatalf("status=%d body=%s", c.Response.StatusCode(), c.Response.Body())
	}
	me := decodeMeResponse(t, c.Response.Body())
	if me.IsSuper {
		t.Fatal("expected isSuper=false for new user")
	}
	if len(me.PlatformRoles) != 0 {
		t.Fatalf("platformRoles=%v, expected empty", me.PlatformRoles)
	}
	if len(me.PermissionCodes) != 0 {
		t.Fatalf("permissionCodes=%v, expected empty for new user", me.PermissionCodes)
	}
	if me.User == nil {
		t.Fatalf("user is nil")
	}
}