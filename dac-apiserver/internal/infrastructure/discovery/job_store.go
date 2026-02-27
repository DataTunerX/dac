package discovery

import (
	"context"
	"sort"
	"sync"
	"time"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// InMemoryJobStore is a minimal job repository for MVP.
// It is intentionally behind the domain.DiscoveryJobRepository interface, so we can swap to DB later.
type InMemoryJobStore struct {
	mu   sync.RWMutex
	jobs map[string]*domain.DiscoveryJob
}

func NewInMemoryJobStore() *InMemoryJobStore {
	return &InMemoryJobStore{
		jobs: make(map[string]*domain.DiscoveryJob),
	}
}

func (s *InMemoryJobStore) Create(ctx context.Context, job *domain.DiscoveryJob) error {
	_ = ctx
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := *job
	s.jobs[job.ID] = &cp
	return nil
}

func (s *InMemoryJobStore) Update(ctx context.Context, job *domain.DiscoveryJob) error {
	_ = ctx
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := *job
	s.jobs[job.ID] = &cp
	return nil
}

func (s *InMemoryJobStore) Get(ctx context.Context, id string) (*domain.DiscoveryJob, error) {
	_ = ctx
	s.mu.RLock()
	defer s.mu.RUnlock()
	job, ok := s.jobs[id]
	if !ok {
		return nil, domain.ErrNotFound
	}
	cp := *job
	// avoid sharing slice backing array
	if job.Services != nil {
		cp.Services = append([]domain.DiscoveredService(nil), job.Services...)
	}
	return &cp, nil
}

func (s *InMemoryJobStore) List(ctx context.Context, req *domain.ListDiscoveryScansRequest) ([]*domain.DiscoveryJob, int, error) {
	_ = ctx
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

	s.mu.RLock()
	defer s.mu.RUnlock()

	// Copy all first, then filter/sort/paginate (small scale, MVP).
	all := make([]*domain.DiscoveryJob, 0, len(s.jobs))
	for _, j := range s.jobs {
		cp := *j
		if j.Services != nil {
			cp.Services = append([]domain.DiscoveredService(nil), j.Services...)
		}
		all = append(all, &cp)
	}

	filtered := make([]*domain.DiscoveryJob, 0, len(all))
	for _, j := range all {
		if req.Target != "" && j.Target != req.Target {
			continue
		}
		if req.Status != "" && j.Status != req.Status {
			continue
		}
		filtered = append(filtered, j)
	}

	// Sort by CreatedAt desc.
	sort.Slice(filtered, func(i, k int) bool {
		return filtered[i].CreatedAt.After(filtered[k].CreatedAt)
	})

	total := len(filtered)
	if offset >= total {
		return []*domain.DiscoveryJob{}, total, nil
	}
	end := offset + limit
	if end > total {
		end = total
	}
	return filtered[offset:end], total, nil
}

func (s *InMemoryJobStore) Delete(ctx context.Context, id string) error {
	_ = ctx
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.jobs[id]; !ok {
		return domain.ErrNotFound
	}
	delete(s.jobs, id)
	return nil
}

// Optional TTL cleanup (not required for correctness).
func (s *InMemoryJobStore) CleanupOlderThan(d time.Duration) {
	cutoff := time.Now().Add(-d)
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, job := range s.jobs {
		if job.UpdatedAt.Before(cutoff) {
			delete(s.jobs, id)
		}
	}
}

