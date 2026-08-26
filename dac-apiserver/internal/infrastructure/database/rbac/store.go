// Package rbac implements the persistence layer for the RBAC module.
//
// It adapts the ent-generated models (tenant, role, permission, membership) to
// the engine interface pkg/rbac.Storage and the management interface
// internal/domain/rbac.Store, keeping ent details out of the usecase layer.
package rbac

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"entgo.io/ent/dialect/sql"
	"github.com/google/uuid"

	domain "github.com/lvyanru/dac-apiserver/internal/domain"
	domainrbac "github.com/lvyanru/dac-apiserver/internal/domain/rbac"
	"github.com/lvyanru/dac-apiserver/internal/ent"
	"github.com/lvyanru/dac-apiserver/internal/ent/permission"
	"github.com/lvyanru/dac-apiserver/internal/ent/platformrole"
	"github.com/lvyanru/dac-apiserver/internal/ent/platformrolepermission"
	"github.com/lvyanru/dac-apiserver/internal/ent/platformuserrole"
	"github.com/lvyanru/dac-apiserver/internal/ent/tenant"
	"github.com/lvyanru/dac-apiserver/internal/ent/tenantnamespace"
	"github.com/lvyanru/dac-apiserver/internal/ent/tenantrole"
	"github.com/lvyanru/dac-apiserver/internal/ent/tenantrolepermission"
	"github.com/lvyanru/dac-apiserver/internal/ent/tenantuser"
	"github.com/lvyanru/dac-apiserver/internal/ent/user"

	eng "github.com/lvyanru/dac-apiserver/pkg/rbac"
)

// rbErrNotFound is the sentinel the engine checks via errors.Is. It is returned
// for every "row absent" case so the engine can deny-by-default without treating
// missing records as infrastructure failures. It wraps both the engine sentinel
// (pkg/rbac.ErrNotFound) and the domain sentinel (domain.ErrNotFound) so that
// engine checks and usecase/domain checks (domain.IsNotFound) both resolve true.
var rbErrNotFound = fmt.Errorf("%w: %w", eng.ErrNotFound, domain.ErrNotFound)

// rbErrAlreadyExists signals a uniqueness conflict through the domain error chain
// so usecases can translate it to the API's ALREADY_EXISTS response.
var rbErrAlreadyExists = domain.ErrAlreadyExists

// rbErrConflict signals a business conflict (deleting a tenant with bindings etc).
var rbErrConflict = domain.ErrConflict

// Store is the ent-backed implementation of the RBAC persistence contracts.
// It must satisfy both the management interface and the engine interface.
type Store struct {
	client *ent.Client
	log    *slog.Logger
}

// NewStore constructs a Store from an ent client.
func NewStore(client *ent.Client, logger *slog.Logger) *Store {
	return &Store{client: client, log: logger}
}

// Compile-time assertions: keep the two contracts honest.
var (
	_ domainrbac.Store = (*Store)(nil)
	_ eng.Storage      = (*Store)(nil)
)

func mustParseUUID(id string) (uuid.UUID, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return uuid.Nil, fmt.Errorf("invalid id %q: %w", id, err)
	}
	return u, nil
}

// isEntNotFound converts an ent not-found error into the engine sentinel so the
// caller (engine or usecase) can distinguish "absent" from "broken".
func isEntNotFound(err error) bool {
	return err != nil && ent.IsNotFound(err)
}

// wrapsErrNotFound returns the engine sentinel if err is an ent not-found.
func wrapsErrNotFound(err error) error {
	if isEntNotFound(err) {
		return rbErrNotFound
	}
	return err
}

// ---- Engine interface (pkg/rbac.Storage) ----

// GetUserPlatformRoles returns every platform role bound to the user.
func (s *Store) GetUserPlatformRoles(ctx context.Context, userID string) ([]eng.PlatformRole, error) {
	uid, err := mustParseUUID(userID)
	if err != nil {
		return nil, err
	}
	rows, err := s.client.PlatformUserRole.Query().
		Where(platformuserrole.UserID(uid)).
		WithRole().
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("query platform user roles: %w", err)
	}
	out := make([]eng.PlatformRole, 0, len(rows))
	for _, r := range rows {
		if r.Edges.Role == nil {
			continue
		}
		out = append(out, eng.PlatformRole{
			ID:      r.Edges.Role.ID.String(),
			Code:    r.Edges.Role.Code,
			Name:    r.Edges.Role.Name,
			IsSuper: r.Edges.Role.IsSuper,
		})
	}
	return out, nil
}

// GetTenantRole returns the tenant-local role bound to the user in the given tenant.
func (s *Store) GetTenantRole(ctx context.Context, userID, tenantID string) (*eng.TenantRole, error) {
	uid, err := mustParseUUID(userID)
	if err != nil {
		return nil, err
	}
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return nil, err
	}
	member, err := s.client.TenantUser.Query().
		Where(tenantuser.UserID(uid), tenantuser.TenantID(tid)).
		WithRole().
		Only(ctx)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	if member.Edges.Role == nil {
		return nil, rbErrNotFound
	}
	return &eng.TenantRole{
		ID:        member.Edges.Role.ID.String(),
		TenantID:  member.Edges.Role.TenantID.String(),
		Code:      member.Edges.Role.Code,
		Name:      member.Edges.Role.Name,
		IsDefault: member.Edges.Role.IsDefault,
	}, nil
}

// ListTenantRolesByUser returns the tenant-local roles bound to a user across
// every tenant they belong to (one role per membership).
func (s *Store) ListTenantRolesByUser(ctx context.Context, userID string) ([]eng.TenantRole, error) {
	uid, err := mustParseUUID(userID)
	if err != nil {
		return nil, err
	}
	rows, err := s.client.TenantUser.Query().
		Where(tenantuser.UserID(uid)).
		WithRole().
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("query memberships with roles: %w", err)
	}
	out := make([]eng.TenantRole, 0, len(rows))
	for _, m := range rows {
		if m.Edges.Role == nil {
			continue
		}
		out = append(out, eng.TenantRole{
			ID:        m.Edges.Role.ID.String(),
			TenantID:  m.Edges.Role.TenantID.String(),
			Code:      m.Edges.Role.Code,
			Name:      m.Edges.Role.Name,
			IsDefault: m.Edges.Role.IsDefault,
		})
	}
	return out, nil
}

// GetRolePermissions returns the joined permission-ID list for a role.
// Platform roles pass the roleID of platform_role; tenant roles pass tenant_role.
func (s *Store) GetRolePermissions(ctx context.Context, roleID string) ([]string, error) {
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return nil, err
	}
	// Collect from both binding tables; a role ID exists in exactly one of them.
	var ids []string

	tr, err := s.client.TenantRolePermission.Query().
		Where(tenantrolepermission.RoleID(rid)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("query tenant role permissions: %w", err)
	}
	for _, r := range tr {
		ids = append(ids, r.PermissionID.String())
	}

	pr, err := s.client.PlatformRolePermission.Query().
		Where(platformrolepermission.RoleID(rid)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("query platform role permissions: %w", err)
	}
	for _, r := range pr {
		ids = append(ids, r.PermissionID.String())
	}

	return ids, nil
}

// PermissionsByCode resolves a permission code to its definitions.
func (s *Store) PermissionsByCode(ctx context.Context, code string) ([]eng.Permission, error) {
	p, err := s.client.Permission.Query().
		Where(permission.Code(code)).
		Only(ctx)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return []eng.Permission{toEnginePermission(p)}, nil
}

// PermissionCodesByIDs resolves permission IDs to their codes.
func (s *Store) PermissionCodesByIDs(ctx context.Context, ids []string) ([]string, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	uuids := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		u, err := mustParseUUID(id)
		if err != nil {
			return nil, err
		}
		uuids = append(uuids, u)
	}
	rows, err := s.client.Permission.Query().
		Where(permission.IDIn(uuids...)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("query permissions by ids: %w", err)
	}
	byID := make(map[string]string, len(rows))
	for _, p := range rows {
		byID[p.ID.String()] = p.Code
	}
	out := make([]string, 0, len(ids))
	for _, id := range ids {
		if code, ok := byID[id]; ok {
			out = append(out, code)
		}
	}
	return out, nil
}

// GetTenantNamespaces returns the namespaces bound to a tenant.
func (s *Store) GetTenantNamespaces(ctx context.Context, tenantID string) ([]string, error) {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return nil, err
	}
	rows, err := s.client.TenantNamespace.Query().
		Where(tenantnamespace.TenantID(tid)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("query tenant namespaces: %w", err)
	}
	out := make([]string, 0, len(rows))
	for _, r := range rows {
		out = append(out, r.Namespace)
	}
	return out, nil
}

// IsTenantActive reports whether the tenant is not disabled. A missing tenant
// is treated as inactive (deny-by-default).
func (s *Store) IsTenantActive(ctx context.Context, tenantID string) (bool, error) {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return false, nil
	}
	t, err := s.client.Tenant.Get(ctx, tid)
	if err != nil {
		if isEntNotFound(err) {
			return false, nil
		}
		return false, fmt.Errorf("get tenant: %w", err)
	}
	return t.Status == "active", nil
}

// TimeNow returns the process clock for cache TTL bookkeeping.
func (s *Store) TimeNow() time.Time {
	return time.Now()
}

// ---- entity converters ----

func toEnginePermission(p *ent.Permission) eng.Permission {
	return eng.Permission{
		ID:          p.ID.String(),
		Code:        p.Code,
		Name:        p.Name,
		Resource:    p.Resource,
		Action:      p.Action,
		HTTPMethod:  p.HTTPMethod,
		HTTPPath:    p.HTTPPath,
		Description: p.Description,
	}
}

func toDomainTenant(t *ent.Tenant) *domainrbac.Tenant {
	return &domainrbac.Tenant{
		ID:          t.ID.String(),
		Code:        t.Code,
		Name:        t.Name,
		Status:      t.Status,
		Description: t.Description,
		CreatedAt:   t.CreatedAt,
		UpdatedAt:   t.UpdatedAt,
	}
}

func toDomainTenantRole(r *ent.TenantRole) *domainrbac.TenantRole {
	return &domainrbac.TenantRole{
		ID:          r.ID.String(),
		TenantID:    r.TenantID.String(),
		Code:        r.Code,
		Name:        r.Name,
		IsDefault:   r.IsDefault,
		Description: r.Description,
		CreatedAt:   r.CreatedAt,
		UpdatedAt:   r.UpdatedAt,
	}
}

func toDomainPlatformRole(r *ent.PlatformRole) *domainrbac.PlatformRole {
	return &domainrbac.PlatformRole{
		ID:          r.ID.String(),
		Code:        r.Code,
		Name:        r.Name,
		IsSuper:     r.IsSuper,
		Description: r.Description,
		CreatedAt:   r.CreatedAt,
		UpdatedAt:   r.UpdatedAt,
	}
}

func toDomainPermission(p *ent.Permission) *domainrbac.Permission {
	return &domainrbac.Permission{
		ID:          p.ID.String(),
		Code:        p.Code,
		Name:        p.Name,
		Resource:    p.Resource,
		Action:      p.Action,
		HTTPMethod:  p.HTTPMethod,
		HTTPPath:    p.HTTPPath,
		Description: p.Description,
		CreatedAt:   p.CreatedAt,
		UpdatedAt:   p.UpdatedAt,
	}
}

// ---- 租户 ----

// ListTenants paginates all tenants ordered by creation time.
func (s *Store) ListTenants(ctx context.Context, offset, limit int) ([]*domainrbac.Tenant, int, error) {
	total, err := s.client.Tenant.Query().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("count tenants: %w", err)
	}
	rows, err := s.client.Tenant.Query().
		Order(ent.Desc(tenant.FieldCreatedAt)).
		Offset(offset).
		Limit(limit).
		All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("list tenants: %w", err)
	}
	out := make([]*domainrbac.Tenant, 0, len(rows))
	for _, r := range rows {
		out = append(out, toDomainTenant(r))
	}
	return out, total, nil
}

// GetTenant fetches a tenant by ID.
func (s *Store) GetTenant(ctx context.Context, tenantID string) (*domainrbac.Tenant, error) {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return nil, err
	}
	t, err := s.client.Tenant.Get(ctx, tid)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return toDomainTenant(t), nil
}

// GetTenantByCode fetches a tenant by its unique code.
func (s *Store) GetTenantByCode(ctx context.Context, code string) (*domainrbac.Tenant, error) {
	t, err := s.client.Tenant.Query().
		Where(tenant.Code(code)).
		Only(ctx)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return toDomainTenant(t), nil
}

// CreateTenant inserts a new tenant.
func (s *Store) CreateTenant(ctx context.Context, t *domainrbac.Tenant) (*domainrbac.Tenant, error) {
	created, err := s.client.Tenant.Create().
		SetCode(t.Code).
		SetName(t.Name).
		SetStatus(t.Status).
		SetNillableDescription(strPtr(t.Description)).
		Save(ctx)
	if err != nil {
		if ent.IsConstraintError(err) {
			return nil, fmt.Errorf("%w: tenant %q already exists", rbErrAlreadyExists, t.Code)
		}
		return nil, fmt.Errorf("create tenant: %w", err)
	}
	return toDomainTenant(created), nil
}

// UpdateTenant updates name/status/description; code is immutable.
func (s *Store) UpdateTenant(ctx context.Context, t *domainrbac.Tenant) (*domainrbac.Tenant, error) {
	tid, err := mustParseUUID(t.ID)
	if err != nil {
		return nil, err
	}
	updated, err := s.client.Tenant.UpdateOneID(tid).
		SetName(t.Name).
		SetStatus(t.Status).
		SetNillableDescription(strPtr(t.Description)).
		Save(ctx)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return toDomainTenant(updated), nil
}

// DeleteTenant removes a tenant. It refuses to run while the tenant has any
// namespaces, roles or members so orphaned authorization rows are impossible.
func (s *Store) DeleteTenant(ctx context.Context, tenantID string) error {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return err
	}
	t, err := s.client.Tenant.Get(ctx, tid)
	if err != nil {
		return wrapsErrNotFound(err)
	}
	if n, _ := t.QueryNamespaces().Count(ctx); n > 0 {
		return fmt.Errorf("%w: tenant still holds %d namespace binding(s)", rbErrConflict, n)
	}
	if n, _ := t.QueryRoles().Count(ctx); n > 0 {
		return fmt.Errorf("%w: tenant still has %d role(s)", rbErrConflict, n)
	}
	if n, _ := t.QueryMembers().Count(ctx); n > 0 {
		return fmt.Errorf("%w: tenant still has %d member(s)", rbErrConflict, n)
	}
	if err := s.client.Tenant.DeleteOneID(tid).Exec(ctx); err != nil {
		return wrapsErrNotFound(err)
	}
	return nil
}

// ---- 租户 namespace ----

// ListTenantNamespaces returns the namespaces a tenant holds.
func (s *Store) ListTenantNamespaces(ctx context.Context, tenantID string) ([]string, error) {
	return s.GetTenantNamespaces(ctx, tenantID)
}

// AddTenantNamespace binds a namespace to a tenant.
func (s *Store) AddTenantNamespace(ctx context.Context, tenantID, namespace string) error {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return err
	}
	if strings.TrimSpace(namespace) == "" {
		return fmt.Errorf("namespace must not be empty")
	}
	// idempotent: unique(tenant, namespace) constraint would reject a duplicate,
	// so surface it as a conflict instead of a raw constraint error.
	exists, err := s.client.TenantNamespace.Query().
		Where(tenantnamespace.TenantID(tid), tenantnamespace.Namespace(namespace)).
		Exist(ctx)
	if err != nil {
		return fmt.Errorf("check namespace binding: %w", err)
	}
	if exists {
		return fmt.Errorf("%w: namespace %q already bound", rbErrAlreadyExists, namespace)
	}
	if _, err := s.client.TenantNamespace.Create().
		SetTenantID(tid).
		SetNamespace(namespace).
		Save(ctx); err != nil {
		return fmt.Errorf("bind namespace: %w", err)
	}
	return nil
}

// RemoveTenantNamespace unbinds a namespace from a tenant.
func (s *Store) RemoveTenantNamespace(ctx context.Context, tenantID, namespace string) error {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return err
	}
	n, err := s.client.TenantNamespace.Delete().
		Where(tenantnamespace.TenantID(tid), tenantnamespace.Namespace(namespace)).
		Exec(ctx)
	if err != nil {
		return fmt.Errorf("unbind namespace: %w", err)
	}
	if n == 0 {
		return rbErrNotFound
	}
	return nil
}

// ---- 租户角色 ----

// ListTenantRoles returns all roles of a tenant.
func (s *Store) ListTenantRoles(ctx context.Context, tenantID string) ([]*domainrbac.TenantRole, error) {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return nil, err
	}
	rows, err := s.client.TenantRole.Query().
		Where(tenantrole.TenantID(tid)).
		Order(ent.Asc(tenantrole.FieldCode)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("list tenant roles: %w", err)
	}
	out := make([]*domainrbac.TenantRole, 0, len(rows))
	for _, r := range rows {
		out = append(out, toDomainTenantRole(r))
	}
	return out, nil
}

// GetTenantRoleByID fetches a tenant role by ID.
func (s *Store) GetTenantRoleByID(ctx context.Context, roleID string) (*domainrbac.TenantRole, error) {
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return nil, err
	}
	r, err := s.client.TenantRole.Get(ctx, rid)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return toDomainTenantRole(r), nil
}

// CreateTenantRole inserts a tenant-local role.
func (s *Store) CreateTenantRole(ctx context.Context, r *domainrbac.TenantRole) (*domainrbac.TenantRole, error) {
	tid, err := mustParseUUID(r.TenantID)
	if err != nil {
		return nil, err
	}
	created, err := s.client.TenantRole.Create().
		SetTenantID(tid).
		SetCode(r.Code).
		SetName(r.Name).
		SetIsDefault(r.IsDefault).
		SetNillableDescription(strPtr(r.Description)).
		Save(ctx)
	if err != nil {
		if ent.IsConstraintError(err) {
			return nil, fmt.Errorf("%w: role %q already exists in tenant", rbErrAlreadyExists, r.Code)
		}
		return nil, fmt.Errorf("create tenant role: %w", err)
	}
	return toDomainTenantRole(created), nil
}

// UpdateTenantRole updates a tenant role's display name, description and default flag.
func (s *Store) UpdateTenantRole(ctx context.Context, r *domainrbac.TenantRole) (*domainrbac.TenantRole, error) {
	rid, err := mustParseUUID(r.ID)
	if err != nil {
		return nil, err
	}
	updated, err := s.client.TenantRole.UpdateOneID(rid).
		SetName(r.Name).
		SetIsDefault(r.IsDefault).
		SetNillableDescription(strPtr(r.Description)).
		Save(ctx)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return toDomainTenantRole(updated), nil
}

// DeleteTenantRole removes a role. Members referencing it must be gone first
// (the usecase layer prevents reassigning members before deletion).
func (s *Store) DeleteTenantRole(ctx context.Context, roleID string) error {
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return err
	}
	if n, err := s.client.TenantUser.Query().Where(tenantuser.RoleID(rid)).Count(ctx); err != nil {
		return fmt.Errorf("count role members: %w", err)
	} else if n > 0 {
		return fmt.Errorf("%w: role still has %d member(s)", rbErrConflict, n)
	}
	if n, err := s.client.TenantRolePermission.Query().Where(tenantrolepermission.RoleID(rid)).Count(ctx); err != nil {
		return fmt.Errorf("count role bindings: %w", err)
	} else if n > 0 {
		// Deleting the role cascades nothing; remove its bindings explicitly.
		if _, err := s.client.TenantRolePermission.Delete().Where(tenantrolepermission.RoleID(rid)).Exec(ctx); err != nil {
			return fmt.Errorf("clear role bindings: %w", err)
		}
	}
	if err := s.client.TenantRole.DeleteOneID(rid).Exec(ctx); err != nil {
		return wrapsErrNotFound(err)
	}
	return nil
}

// ---- 租户成员 ----

// ListTenantMembers paginates members with the joined role code.
func (s *Store) ListTenantMembers(ctx context.Context, tenantID string, offset, limit int) ([]*domainrbac.TenantMember, int, error) {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return nil, 0, err
	}
	total, err := s.client.TenantUser.Query().Where(tenantuser.TenantID(tid)).Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("count tenant members: %w", err)
	}
	rows, err := s.client.TenantUser.Query().
		Where(tenantuser.TenantID(tid)).
		WithRole().
		Order(ent.Desc(tenantuser.FieldCreatedAt)).
		Offset(offset).
		Limit(limit).
		All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("list tenant members: %w", err)
	}
	out := make([]*domainrbac.TenantMember, 0, len(rows))
	for _, m := range rows {
		member := &domainrbac.TenantMember{
			ID:        m.ID.String(),
			TenantID:  m.TenantID.String(),
			UserID:    m.UserID.String(),
			RoleID:    m.RoleID.String(),
			CreatedAt: m.CreatedAt,
		}
		if m.Edges.Role != nil {
			member.RoleCode = m.Edges.Role.Code
		}
		out = append(out, member)
	}
	return out, total, nil
}

// GetTenantMembership fetches a user's membership in a tenant.
func (s *Store) GetTenantMembership(ctx context.Context, tenantID, userID string) (*domainrbac.TenantMember, error) {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return nil, err
	}
	uid, err := mustParseUUID(userID)
	if err != nil {
		return nil, err
	}
	m, err := s.client.TenantUser.Query().
		Where(tenantuser.TenantID(tid), tenantuser.UserID(uid)).
		WithRole().
		Only(ctx)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	member := &domainrbac.TenantMember{
		ID:        m.ID.String(),
		TenantID:  m.TenantID.String(),
		UserID:    m.UserID.String(),
		RoleID:    m.RoleID.String(),
		CreatedAt: m.CreatedAt,
	}
	if m.Edges.Role != nil {
		member.RoleCode = m.Edges.Role.Code
	}
	return member, nil
}

// ListTenantIDsByUser returns the IDs of the tenants a user belongs to.
func (s *Store) ListTenantIDsByUser(ctx context.Context, userID string) ([]string, error) {
	uid, err := mustParseUUID(userID)
	if err != nil {
		return nil, err
	}
	rows, err := s.client.TenantUser.Query().
		Where(tenantuser.UserID(uid)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("list memberships: %w", err)
	}
	out := make([]string, 0, len(rows))
	for _, m := range rows {
		out = append(out, m.TenantID.String())
	}
	return out, nil
}

// AddTenantMember adds a user to a tenant with the given role.
func (s *Store) AddTenantMember(ctx context.Context, tenantID, userID, roleID string) (*domainrbac.TenantMember, error) {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return nil, err
	}
	uid, err := mustParseUUID(userID)
	if err != nil {
		return nil, err
	}
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return nil, err
	}
	created, err := s.client.TenantUser.Create().
		SetTenantID(tid).
		SetUserID(uid).
		SetRoleID(rid).
		Save(ctx)
	if err != nil {
		if ent.IsConstraintError(err) {
			return nil, fmt.Errorf("%w: user already a member of this tenant", rbErrAlreadyExists)
		}
		return nil, fmt.Errorf("add tenant member: %w", err)
	}
	return &domainrbac.TenantMember{
		ID:        created.ID.String(),
		TenantID:  tid.String(),
		UserID:    uid.String(),
		RoleID:    rid.String(),
		CreatedAt: created.CreatedAt,
	}, nil
}

// ChangeTenantMemberRole rebinds a member to another role in the same tenant.
func (s *Store) ChangeTenantMemberRole(ctx context.Context, tenantID, userID, roleID string) error {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return err
	}
	uid, err := mustParseUUID(userID)
	if err != nil {
		return err
	}
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return err
	}
	n, err := s.client.TenantUser.Update().
		Where(tenantuser.TenantID(tid), tenantuser.UserID(uid)).
		SetRoleID(rid).
		Save(ctx)
	if err != nil {
		return wrapsErrNotFound(err)
	}
	if n == 0 {
		return rbErrNotFound
	}
	return nil
}

// RemoveTenantMember removes a user from a tenant.
func (s *Store) RemoveTenantMember(ctx context.Context, tenantID, userID string) error {
	tid, err := mustParseUUID(tenantID)
	if err != nil {
		return err
	}
	uid, err := mustParseUUID(userID)
	if err != nil {
		return err
	}
	n, err := s.client.TenantUser.Delete().
		Where(tenantuser.TenantID(tid), tenantuser.UserID(uid)).
		Exec(ctx)
	if err != nil {
		return fmt.Errorf("remove tenant member: %w", err)
	}
	if n == 0 {
		return rbErrNotFound
	}
	return nil
}

// ListUsersNotInAnyTenant returns user IDs who are not assigned to any tenant.
func (s *Store) ListUsersNotInAnyTenant(ctx context.Context) ([]string, error) {
	// Collect all user IDs that already have a tenant membership.
	rows, err := s.client.TenantUser.Query().All(ctx)
	if err != nil {
		return nil, fmt.Errorf("list tenant users: %w", err)
	}
	assigned := make(map[string]bool, len(rows))
	for _, m := range rows {
		assigned[m.UserID.String()] = true
	}

	// Fetch all platform users (excluding soft-deleted and the built-in admin).
	users, err := s.client.User.Query().
		Where(func(s *sql.Selector) { s.Where(sql.IsNull("deleted_at")) }).
		Where(user.UsernameNEQ("admin")).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("list users: %w", err)
	}

	out := make([]string, 0, len(users))
	for _, u := range users {
		if !assigned[u.ID.String()] {
			out = append(out, u.ID.String())
		}
	}
	return out, nil
}

// ---- 平台角色 ----

// ListPlatformRoles returns all platform roles.
func (s *Store) ListPlatformRoles(ctx context.Context) ([]*domainrbac.PlatformRole, error) {
	rows, err := s.client.PlatformRole.Query().
		Order(ent.Asc(platformrole.FieldCode)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("list platform roles: %w", err)
	}
	out := make([]*domainrbac.PlatformRole, 0, len(rows))
	for _, r := range rows {
		out = append(out, toDomainPlatformRole(r))
	}
	return out, nil
}

// GetPlatformRole fetches a platform role by ID.
func (s *Store) GetPlatformRole(ctx context.Context, roleID string) (*domainrbac.PlatformRole, error) {
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return nil, err
	}
	r, err := s.client.PlatformRole.Get(ctx, rid)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return toDomainPlatformRole(r), nil
}

// CreatePlatformRole inserts a platform role.
func (s *Store) CreatePlatformRole(ctx context.Context, r *domainrbac.PlatformRole) (*domainrbac.PlatformRole, error) {
	created, err := s.client.PlatformRole.Create().
		SetCode(r.Code).
		SetName(r.Name).
		SetIsSuper(r.IsSuper).
		SetNillableDescription(strPtr(r.Description)).
		Save(ctx)
	if err != nil {
		if ent.IsConstraintError(err) {
			return nil, fmt.Errorf("%w: platform role %q already exists", rbErrAlreadyExists, r.Code)
		}
		return nil, fmt.Errorf("create platform role: %w", err)
	}
	return toDomainPlatformRole(created), nil
}

// UpdatePlatformRole updates a platform role's name/super flag/description.
func (s *Store) UpdatePlatformRole(ctx context.Context, r *domainrbac.PlatformRole) (*domainrbac.PlatformRole, error) {
	rid, err := mustParseUUID(r.ID)
	if err != nil {
		return nil, err
	}
	updated, err := s.client.PlatformRole.UpdateOneID(rid).
		SetName(r.Name).
		SetIsSuper(r.IsSuper).
		SetNillableDescription(strPtr(r.Description)).
		Save(ctx)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return toDomainPlatformRole(updated), nil
}

// DeletePlatformRole removes a platform role; super-admin holders are protected
// by the usecase layer, storage only enforces no referencing users remain.
func (s *Store) DeletePlatformRole(ctx context.Context, roleID string) error {
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return err
	}
	if n, err := s.client.PlatformUserRole.Query().Where(platformuserrole.RoleID(rid)).Count(ctx); err != nil {
		return fmt.Errorf("count platform role users: %w", err)
	} else if n > 0 {
		return fmt.Errorf("%w: platform role still has %d user(s)", rbErrConflict, n)
	}
	if n, err := s.client.PlatformRolePermission.Query().Where(platformrolepermission.RoleID(rid)).Count(ctx); err != nil {
		return fmt.Errorf("count platform role bindings: %w", err)
	} else if n > 0 {
		if _, err := s.client.PlatformRolePermission.Delete().Where(platformrolepermission.RoleID(rid)).Exec(ctx); err != nil {
			return fmt.Errorf("clear platform role bindings: %w", err)
		}
	}
	if err := s.client.PlatformRole.DeleteOneID(rid).Exec(ctx); err != nil {
		return wrapsErrNotFound(err)
	}
	return nil
}

// ---- 平台角色 ↔ 用户 ----

// ListPlatformRoleUsers returns the user IDs bound to a platform role.
func (s *Store) ListPlatformRoleUsers(ctx context.Context, roleID string) ([]string, error) {
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return nil, err
	}
	rows, err := s.client.PlatformUserRole.Query().
		Where(platformuserrole.RoleID(rid)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("list platform role users: %w", err)
	}
	out := make([]string, 0, len(rows))
	for _, r := range rows {
		out = append(out, r.UserID.String())
	}
	return out, nil
}

// AssignPlatformRole binds a user to a platform role (idempotent).
func (s *Store) AssignPlatformRole(ctx context.Context, userID, roleID string) error {
	uid, err := mustParseUUID(userID)
	if err != nil {
		return err
	}
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return err
	}
	exists, err := s.client.PlatformUserRole.Query().
		Where(platformuserrole.UserID(uid), platformuserrole.RoleID(rid)).
		Exist(ctx)
	if err != nil {
		return fmt.Errorf("check platform user role: %w", err)
	}
	if exists {
		return nil
	}
	if _, err := s.client.PlatformUserRole.Create().
		SetUserID(uid).
		SetRoleID(rid).
		Save(ctx); err != nil {
		if ent.IsConstraintError(err) {
			return nil // concurrent duplicate; idempotent by contract
		}
		return fmt.Errorf("assign platform role: %w", err)
	}
	return nil
}

// RevokePlatformRole removes a user from a platform role.
func (s *Store) RevokePlatformRole(ctx context.Context, userID, roleID string) error {
	uid, err := mustParseUUID(userID)
	if err != nil {
		return err
	}
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return err
	}
	n, err := s.client.PlatformUserRole.Delete().
		Where(platformuserrole.UserID(uid), platformuserrole.RoleID(rid)).
		Exec(ctx)
	if err != nil {
		return fmt.Errorf("revoke platform role: %w", err)
	}
	if n == 0 {
		return rbErrNotFound
	}
	return nil
}

// ---- 权限点 ----

// ListPermissions returns the full permission catalog for the UI to render.
func (s *Store) ListPermissions(ctx context.Context) ([]*domainrbac.Permission, error) {
	rows, err := s.client.Permission.Query().
		Order(ent.Asc(permission.FieldResource), ent.Asc(permission.FieldAction)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("list permissions: %w", err)
	}
	out := make([]*domainrbac.Permission, 0, len(rows))
	for _, p := range rows {
		out = append(out, toDomainPermission(p))
	}
	return out, nil
}

// GetPermissionByCode fetches a permission by its unique code.
func (s *Store) GetPermissionByCode(ctx context.Context, code string) (*domainrbac.Permission, error) {
	p, err := s.client.Permission.Query().
		Where(permission.Code(code)).
		Only(ctx)
	if err != nil {
		return nil, wrapsErrNotFound(err)
	}
	return toDomainPermission(p), nil
}

// UpsertPermission inserts or updates a permission definition (used by the seeder).
func (s *Store) UpsertPermission(ctx context.Context, p *domainrbac.Permission) error {
	existing, err := s.client.Permission.Query().
		Where(permission.Code(p.Code)).
		Only(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return fmt.Errorf("lookup permission %s: %w", p.Code, err)
	}
	if ent.IsNotFound(err) {
		_, err = s.client.Permission.Create().SetCode(p.Code).SetName(p.Name).
			SetResource(p.Resource).SetAction(p.Action).SetHTTPMethod(p.HTTPMethod).
			SetHTTPPath(p.HTTPPath).SetNillableDescription(strPtr(p.Description)).
			Save(ctx)
		if err != nil {
			return fmt.Errorf("create permission %s: %w", p.Code, err)
		}
		return nil
	}
	if _, err := s.client.Permission.UpdateOneID(existing.ID).
		SetName(p.Name).
		SetResource(p.Resource).
		SetAction(p.Action).
		SetHTTPMethod(p.HTTPMethod).
		SetHTTPPath(p.HTTPPath).
		SetNillableDescription(strPtr(p.Description)).
		Save(ctx); err != nil {
		return fmt.Errorf("update permission %s: %w", p.Code, err)
	}
	return nil
}

// ---- 角色 ↔ 权限 ----

// SetRolePermissions replaces the permission set of a role in one transaction.
// tenantID must be empty for platform roles; it is used to pick the binding table.
func (s *Store) SetRolePermissions(ctx context.Context, roleID, tenantID string, permissionIDs []string) error {
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return err
	}
	perms := make([]uuid.UUID, 0, len(permissionIDs))
	for _, id := range permissionIDs {
		u, err := mustParseUUID(id)
		if err != nil {
			return err
		}
		perms = append(perms, u)
	}

	tx, err := s.client.Tx(ctx)
	if err != nil {
		return fmt.Errorf("begin role permission tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if tenantID == "" {
		if _, err := tx.PlatformRolePermission.Delete().
			Where(platformrolepermission.RoleID(rid)).
			Exec(ctx); err != nil {
			return fmt.Errorf("clear platform role permissions: %w", err)
		}
		for _, pid := range perms {
			if _, err := tx.PlatformRolePermission.Create().
				SetRoleID(rid).
				SetPermissionID(pid).
				Save(ctx); err != nil {
				return fmt.Errorf("bind platform role permission: %w", err)
			}
		}
	} else {
		if _, err := tx.TenantRolePermission.Delete().
			Where(tenantrolepermission.RoleID(rid)).
			Exec(ctx); err != nil {
			return fmt.Errorf("clear tenant role permissions: %w", err)
		}
		for _, pid := range perms {
			if _, err := tx.TenantRolePermission.Create().
				SetRoleID(rid).
				SetPermissionID(pid).
				Save(ctx); err != nil {
				return fmt.Errorf("bind tenant role permission: %w", err)
			}
		}
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit role permission tx: %w", err)
	}
	return nil
}

// GetRolePermissionIDs returns the permission IDs bound to a role.
func (s *Store) GetRolePermissionIDs(ctx context.Context, roleID string, isPlatform bool) ([]string, error) {
	rid, err := mustParseUUID(roleID)
	if err != nil {
		return nil, err
	}
	if isPlatform {
		rows, err := s.client.PlatformRolePermission.Query().
			Where(platformrolepermission.RoleID(rid)).
			All(ctx)
		if err != nil {
			return nil, fmt.Errorf("list platform role permissions: %w", err)
		}
		out := make([]string, 0, len(rows))
		for _, r := range rows {
			out = append(out, r.PermissionID.String())
		}
		return out, nil
	}
	rows, err := s.client.TenantRolePermission.Query().
		Where(tenantrolepermission.RoleID(rid)).
		All(ctx)
	if err != nil {
		return nil, fmt.Errorf("list tenant role permissions: %w", err)
	}
	out := make([]string, 0, len(rows))
	for _, r := range rows {
		out = append(out, r.PermissionID.String())
	}
	return out, nil
}

// strPtr returns a *string for ent's nillable setters.
func strPtr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
