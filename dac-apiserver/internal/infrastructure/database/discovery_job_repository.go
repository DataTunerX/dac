package database

import (
	"context"
	"strings"

	"github.com/google/uuid"
	"github.com/lvyanru/dac-apiserver/internal/domain"
	"github.com/lvyanru/dac-apiserver/internal/ent"
	entdiscovery "github.com/lvyanru/dac-apiserver/internal/ent/discoveryjob"
	entschema "github.com/lvyanru/dac-apiserver/internal/ent/schema"
)

type discoveryJobRepository struct {
	client *ent.Client
}

func NewDiscoveryJobRepository(client *ent.Client) domain.DiscoveryJobRepository {
	return &discoveryJobRepository{client: client}
}

func (r *discoveryJobRepository) Create(ctx context.Context, job *domain.DiscoveryJob) error {
	if job == nil {
		return domain.ErrInvalidInput
	}
	id, err := uuid.Parse(job.ID)
	if err != nil {
		return domain.NewInvalidInputError("invalid discovery job id")
	}

	_, err = r.client.DiscoveryJob.Create().
		SetID(id).
		SetTarget(job.Target).
		SetNillablePortsSpec(optionalString(job.PortsSpec)).
		SetStatus(string(job.Status)).
		SetNillableName(optionalString(job.Name)).
		SetNillableError(optionalString(job.Error)).
		SetNillableStartedAt(job.StartedAt).
		SetNillableFinishedAt(job.FinishedAt).
		SetServices(toEntServices(job.Services)).
		Save(ctx)
	if err != nil {
		return err
	}
	return nil
}

func (r *discoveryJobRepository) Update(ctx context.Context, job *domain.DiscoveryJob) error {
	if job == nil {
		return domain.ErrInvalidInput
	}
	id, err := uuid.Parse(job.ID)
	if err != nil {
		return domain.NewInvalidInputError("invalid discovery job id")
	}

	u := r.client.DiscoveryJob.UpdateOneID(id).
		SetTarget(job.Target).
		SetStatus(string(job.Status)).
		SetNillableError(optionalString(job.Error)).
		SetNillableStartedAt(job.StartedAt).
		SetNillableFinishedAt(job.FinishedAt).
		SetServices(toEntServices(job.Services))

	if job.PortsSpec != "" {
		u.SetPortsSpec(job.PortsSpec)
	} else {
		u.ClearPortsSpec()
	}
	if job.Name != "" {
		u.SetName(job.Name)
	} else {
		u.ClearName()
	}

	_, err = u.Save(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			return domain.ErrNotFound
		}
		return err
	}
	return nil
}

func (r *discoveryJobRepository) Get(ctx context.Context, id string) (*domain.DiscoveryJob, error) {
	uid, err := uuid.Parse(id)
	if err != nil {
		return nil, domain.NewInvalidInputError("invalid discovery job id")
	}
	row, err := r.client.DiscoveryJob.Get(ctx, uid)
	if err != nil {
		if ent.IsNotFound(err) {
			return nil, domain.ErrNotFound
		}
		return nil, err
	}
	return toDomainDiscoveryJob(row), nil
}

func (r *discoveryJobRepository) List(ctx context.Context, req *domain.ListDiscoveryScansRequest) ([]*domain.DiscoveryJob, int, error) {
	if req == nil {
		req = &domain.ListDiscoveryScansRequest{}
	}
	limit := req.Limit
	if limit <= 0 {
		limit = 50
	}
	if limit > 200 {
		limit = 200
	}
	offset := req.Offset
	if offset < 0 {
		offset = 0
	}

	q := r.client.DiscoveryJob.Query()

	if t := strings.TrimSpace(req.Target); t != "" {
		q = q.Where(entdiscovery.TargetEQ(t))
	}
	if req.Status != "" {
		q = q.Where(entdiscovery.StatusEQ(string(req.Status)))
	}

	total, err := q.Count(ctx)
	if err != nil {
		return nil, 0, err
	}

	rows, err := q.Order(ent.Desc(entdiscovery.FieldCreatedAt)).Offset(offset).Limit(limit).All(ctx)
	if err != nil {
		return nil, 0, err
	}

	items := make([]*domain.DiscoveryJob, 0, len(rows))
	for _, row := range rows {
		items = append(items, toDomainDiscoveryJob(row))
	}
	return items, total, nil
}

func (r *discoveryJobRepository) Delete(ctx context.Context, id string) error {
	uid, err := uuid.Parse(id)
	if err != nil {
		return domain.NewInvalidInputError("invalid discovery job id")
	}
	err = r.client.DiscoveryJob.DeleteOneID(uid).Exec(ctx)
	if err != nil {
		if ent.IsNotFound(err) {
			return domain.ErrNotFound
		}
		return err
	}
	return nil
}

func toEntServices(services []domain.DiscoveredService) []entschema.DiscoveryService {
	if len(services) == 0 {
		return []entschema.DiscoveryService{}
	}
	out := make([]entschema.DiscoveryService, 0, len(services))
	for _, s := range services {
		out = append(out, entschema.DiscoveryService{
			Host:        s.Host,
			Port:        s.Port,
			Protocol:    s.Protocol,
			ServiceType: s.ServiceType,
			Product:     s.Product,
			Version:     s.Version,
			TLS:         s.TLS,
			Metadata:    s.Metadata,
		})
	}
	return out
}

func toDomainDiscoveryJob(row *ent.DiscoveryJob) *domain.DiscoveryJob {
	job := &domain.DiscoveryJob{
		ID:        row.ID.String(),
		Name:      row.Name,
		Target:    row.Target,
		PortsSpec: row.PortsSpec,
		Status:    domain.DiscoveryJobStatus(row.Status),
		Error:     row.Error,
		CreatedAt: row.CreatedAt,
		UpdatedAt: row.UpdatedAt,
	}
	if row.StartedAt != nil {
		job.StartedAt = row.StartedAt
	}
	if row.FinishedAt != nil {
		job.FinishedAt = row.FinishedAt
	}
	// Services is stored as JSON; ent typed as []map[string]any by our repo set.
	// Convert.
	if len(row.Services) > 0 {
		job.Services = fromEntServices(row.Services)
	}
	return job
}

func fromEntServices(v []entschema.DiscoveryService) []domain.DiscoveredService {
	out := make([]domain.DiscoveredService, 0, len(v))
	for _, s := range v {
		out = append(out, domain.DiscoveredService{
			Host:        s.Host,
			Port:        s.Port,
			Protocol:    s.Protocol,
			ServiceType: s.ServiceType,
			Product:     s.Product,
			Version:     s.Version,
			TLS:         s.TLS,
			Metadata:    s.Metadata,
		})
	}
	return out
}

func optionalString(s string) *string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	v := s
	return &v
}

