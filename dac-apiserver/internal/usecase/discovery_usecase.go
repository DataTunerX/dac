package usecase

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/lvyanru/dac-apiserver/internal/domain"
	infra "github.com/lvyanru/dac-apiserver/internal/infrastructure/discovery"
)

type discoveryUsecase struct {
	repo    domain.DiscoveryJobRepository
	scanner *infra.Scanner
	logger  *slog.Logger
}

func NewDiscoveryUsecase(repo domain.DiscoveryJobRepository, scanner *infra.Scanner, logger *slog.Logger) domain.DiscoveryUsecase {
	return &discoveryUsecase{repo: repo, scanner: scanner, logger: logger}
}

func (u *discoveryUsecase) StartScan(ctx context.Context, req *domain.StartDiscoveryScanRequest) (*domain.DiscoveryJob, error) {
	if req == nil || req.Target == "" {
		return nil, domain.NewInvalidInputError("target is required")
	}

	job := &domain.DiscoveryJob{
		ID:        uuid.NewString(),
		Target:    req.Target,
		PortsSpec: req.PortsSpec,
		Status:    domain.DiscoveryJobPending,
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
	if err := u.repo.Create(ctx, job); err != nil {
		return nil, err
	}

	// Run async
	go u.run(job.ID, req)
	return job, nil
}

func (u *discoveryUsecase) GetScan(ctx context.Context, id string) (*domain.DiscoveryJob, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	return u.repo.Get(ctx, id)
}

func (u *discoveryUsecase) ListScans(ctx context.Context, req *domain.ListDiscoveryScansRequest) (*domain.ListDiscoveryScansResult, error) {
	if req == nil {
		req = &domain.ListDiscoveryScansRequest{}
	}
	// Default pagination for UX.
	if req.Limit <= 0 {
		req.Limit = 50
	}
	if req.Limit > 200 {
		req.Limit = 200
	}
	if req.Offset < 0 {
		req.Offset = 0
	}

	items, total, err := u.repo.List(ctx, req)
	if err != nil {
		return nil, err
	}
	return &domain.ListDiscoveryScansResult{Items: items, Total: total}, nil
}

func (u *discoveryUsecase) UpdateScan(ctx context.Context, id string, req *domain.UpdateDiscoveryScanRequest) (*domain.DiscoveryJob, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	if req == nil {
		return nil, domain.ErrInvalidInput
	}
	job, err := u.repo.Get(ctx, id)
	if err != nil {
		return nil, err
	}
	if req.Name != "" {
		job.Name = req.Name
	}
	job.UpdatedAt = time.Now()
	if err := u.repo.Update(ctx, job); err != nil {
		return nil, err
	}
	return job, nil
}

func (u *discoveryUsecase) DeleteScan(ctx context.Context, id string) error {
	if id == "" {
		return domain.NewInvalidInputError("id is required")
	}
	return u.repo.Delete(ctx, id)
}

func (u *discoveryUsecase) run(jobID string, req *domain.StartDiscoveryScanRequest) {
	ctx, cancel := context.WithTimeout(context.Background(), req.Timeout)
	if req.Timeout <= 0 {
		ctx, cancel = context.WithTimeout(context.Background(), 30*time.Second)
	}
	defer cancel()

	job, err := u.repo.Get(ctx, jobID)
	if err != nil {
		u.logger.Error("discovery job load failed", "job_id", jobID, "error", err)
		return
	}

	now := time.Now()
	job.Status = domain.DiscoveryJobRunning
	job.StartedAt = &now
	job.UpdatedAt = time.Now()
	_ = u.repo.Update(ctx, job)

	ports, err := infra.ParsePortSpec(req.PortsSpec)
	if err != nil {
		u.fail(ctx, job, "invalid portsSpec: "+err.Error())
		return
	}
	if len(ports) == 0 {
		// Design: empty portsSpec means scan all ports.
		ports = infra.AllPorts()
	}

	targets, err := infra.ParseTargets(req.Target)
	if err != nil {
		u.fail(ctx, job, "invalid target: "+err.Error())
		return
	}

	concurrency := req.Concurrency
	if concurrency <= 0 {
		concurrency = 128
	}
	if concurrency > 1024 {
		concurrency = 1024
	}

	// Guardrail: expanding IP segments + scanning all ports can create an
	// unbounded amount of work. Keep it bounded for predictable resource usage.
	const maxScanTasks = 1_000_000
	totalTasks := uint64(len(targets)) * uint64(len(ports))
	if totalTasks == 0 {
		u.fail(ctx, job, "no scan tasks")
		return
	}
	if totalTasks > maxScanTasks {
		u.fail(ctx, job, fmt.Sprintf("too many scan tasks (%d), please narrow target/portsSpec", totalTasks))
		return
	}

	type task struct {
		host string
		port int
	}
	taskCh := make(chan task, concurrency*4)
	resCh := make(chan *domain.DiscoveredService, concurrency*4)

	var wg sync.WaitGroup
	services := make([]domain.DiscoveredService, 0, 64)
	collectDone := make(chan struct{})
	go func() {
		defer close(collectDone)
		for svc := range resCh {
			if svc == nil {
				continue
			}
			services = append(services, *svc)
		}
	}()

	worker := func() {
		defer wg.Done()
		for t := range taskCh {
			if ctx.Err() != nil {
				continue
			}
			svc, ok := u.scanner.ScanPort(ctx, t.host, t.port)
			if ok && svc != nil {
				select {
				case resCh <- svc:
				case <-ctx.Done():
					return
				}
			}
		}
	}

	wg.Add(concurrency)
	for i := 0; i < concurrency; i++ {
		go worker()
	}

	aborted := false
	for _, host := range targets {
		for _, port := range ports {
			select {
			case <-ctx.Done():
				aborted = true
				break
			case taskCh <- task{host: host, port: port}:
			}
		}
		if aborted {
			break
		}
	}

	close(taskCh)
	wg.Wait()
	close(resCh)
	<-collectDone

	if aborted || ctx.Err() != nil {
		u.fail(context.Background(), job, "scan cancelled: "+ctx.Err().Error())
		return
	}

	finish := time.Now()
	// IMPORTANT: preserve any user-updated metadata (e.g. Name) that may have been
	// updated while the scan was running. The in-memory `job` was loaded before
	// those updates and would otherwise overwrite them.
	latest, err := u.repo.Get(ctx, jobID)
	if err != nil {
		// Fall back to best-effort update (do not fail the job silently).
		latest = job
	}
	latest.Services = services
	latest.Status = domain.DiscoveryJobSucceeded
	latest.FinishedAt = &finish
	latest.UpdatedAt = time.Now()
	_ = u.repo.Update(ctx, latest)
}

func (u *discoveryUsecase) fail(ctx context.Context, job *domain.DiscoveryJob, msg string) {
	finish := time.Now()
	// Same reasoning as success path: preserve user metadata like Name.
	latest, err := u.repo.Get(ctx, job.ID)
	if err != nil {
		latest = job
	}
	latest.Status = domain.DiscoveryJobFailed
	latest.Error = msg
	latest.FinishedAt = &finish
	latest.UpdatedAt = time.Now()
	_ = u.repo.Update(ctx, latest)
}

