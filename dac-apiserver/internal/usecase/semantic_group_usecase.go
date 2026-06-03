package usecase

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"strings"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

const semanticGroupsVectorCollection = "semantic_groups"

type semanticGroupUsecase struct {
	dsClient domain.DataServicesClient
	grouper  domain.SemanticGrouperClient
	logger   *slog.Logger
}

func NewSemanticGroupUsecase(dsClient domain.DataServicesClient, grouper domain.SemanticGrouperClient, logger *slog.Logger) domain.SemanticGroupUsecase {
	if logger == nil {
		logger = slog.Default()
	}
	return &semanticGroupUsecase{
		dsClient: dsClient,
		grouper:  grouper,
		logger:   logger,
	}
}

func (u *semanticGroupUsecase) Create(ctx context.Context, req *domain.CreateSemanticGroupRequest) (*domain.SemanticGroup, error) {
	if req == nil || req.GroupName == "" {
		return nil, domain.NewInvalidInputError("groupName is required")
	}
	dsReq := map[string]any{
		"group_name":  req.GroupName,
		"description": req.Description,
		"agent_card":  req.AgentCard,
		"version":     req.Version,
	}
	created, err := u.dsClient.CreateSemanticGroup(ctx, dsReq)
	if err != nil {
		return nil, err
	}
	u.refreshSemanticGroupVector(ctx, created.ID)
	return created, nil
}

func (u *semanticGroupUsecase) BatchCreate(ctx context.Context, req []domain.CreateSemanticGroupRequest) (int, error) {
	if len(req) == 0 {
		return 0, domain.NewInvalidInputError("empty request")
	}
	dsReq := make([]map[string]any, 0, len(req))
	for _, r := range req {
		if r.GroupName == "" {
			return 0, domain.NewInvalidInputError("groupName is required")
		}
		dsReq = append(dsReq, map[string]any{
			"group_name":  r.GroupName,
			"description": r.Description,
			"agent_card":  r.AgentCard,
			"version":     r.Version,
		})
	}
	return u.dsClient.BatchCreateSemanticGroups(ctx, dsReq)
}

func (u *semanticGroupUsecase) Get(ctx context.Context, id string) (*domain.SemanticGroup, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.GetSemanticGroup(ctx, id)
}

func (u *semanticGroupUsecase) GetWithMembers(ctx context.Context, id string) (*domain.SemanticGroupWithMembers, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.GetSemanticGroupWithMembers(ctx, id)
}

func (u *semanticGroupUsecase) List(ctx context.Context, limit, offset int) ([]domain.SemanticGroup, int, error) {
	if limit <= 0 {
		limit = 50
	}
	if offset < 0 {
		offset = 0
	}
	page := offset/limit + 1
	pageSize := limit
	return u.dsClient.ListSemanticGroups(ctx, page, pageSize)
}

func (u *semanticGroupUsecase) ListRoots(ctx context.Context) ([]domain.SemanticGroup, int, error) {
	return u.dsClient.ListSemanticGroupRoots(ctx)
}

func (u *semanticGroupUsecase) Update(ctx context.Context, id string, req *domain.UpdateSemanticGroupRequest) (*domain.SemanticGroup, error) {
	if id == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	if req == nil {
		return nil, domain.NewInvalidInputError("empty request")
	}
	dsReq := map[string]any{}
	if req.GroupName != nil {
		dsReq["group_name"] = *req.GroupName
	}
	if req.Description != nil {
		dsReq["description"] = *req.Description
	}
	if req.AgentCard != nil {
		dsReq["agent_card"] = *req.AgentCard
	}
	if req.Version != nil {
		dsReq["version"] = *req.Version
	}
	if len(dsReq) == 0 {
		return u.dsClient.GetSemanticGroup(ctx, id)
	}
	updated, err := u.dsClient.UpdateSemanticGroup(ctx, id, dsReq)
	if err != nil {
		return nil, err
	}
	u.refreshSemanticGroupVector(ctx, id)
	return updated, nil
}

func (u *semanticGroupUsecase) refreshSemanticGroupVector(ctx context.Context, groupID string) {
	withMembers, err := u.dsClient.GetSemanticGroupWithMembers(ctx, groupID)
	if err != nil {
		u.logger.Warn("semantic group pgvector refresh: load members failed", "group_id", groupID, "error", err)
		return
	}
	group := withMembers.Group
	pageContent := buildSemanticGroupVectorText(group.GroupName, group.Description, withMembers.Members)

	oldIDs, err := u.dsClient.GetVectorDocumentIDsByMetadataField(ctx, semanticGroupsVectorCollection, "group_id", groupID)
	if err != nil {
		u.logger.Warn("semantic group pgvector refresh: list old vectors failed", "group_id", groupID, "error", err)
		oldIDs = nil
	}

	doc := domain.VectorDocumentInput{
		PageContent: pageContent,
		Metadata: map[string]any{
			"group_id":   groupID,
			"group_name": group.GroupName,
		},
	}
	if err := u.dsClient.AddVectorDocuments(ctx, semanticGroupsVectorCollection, []domain.VectorDocumentInput{doc}); err != nil {
		u.logger.Warn("semantic group pgvector refresh: add vectors failed", "group_id", groupID, "error", err)
		return
	}
	if len(oldIDs) > 0 {
		if err := u.dsClient.DeleteVectorDocumentsByIDs(ctx, semanticGroupsVectorCollection, oldIDs); err != nil {
			u.logger.Warn("semantic group pgvector refresh: delete stale vectors failed", "group_id", groupID, "error", err)
			return
		}
	}
	u.logger.Info("semantic group pgvector refreshed", "group_id", groupID)
}

func buildSemanticGroupVectorText(groupName, description string, members []domain.SemanticGroupMemberDetail) string {
	parts := []string{fmt.Sprintf("语义组名称: %s", groupName)}
	if strings.TrimSpace(description) != "" {
		parts = append(parts, fmt.Sprintf("描述: %s", description))
	}
	idSet := make(map[string]struct{})
	for _, member := range members {
		sdID := strings.TrimSpace(member.Relation.SemanticDomainID)
		if sdID == "" {
			continue
		}
		idSet[sdID] = struct{}{}
	}
	if len(idSet) > 0 {
		ids := make([]string, 0, len(idSet))
		for id := range idSet {
			ids = append(ids, id)
		}
		sort.Strings(ids)
		parts = append(parts, fmt.Sprintf("成员语义域ID: %s", strings.Join(ids, ", ")))
	}
	return strings.Join(parts, "\n")
}

func (u *semanticGroupUsecase) Delete(ctx context.Context, id string) error {
	if id == "" {
		return domain.NewInvalidInputError("id is required")
	}
	if err := u.dsClient.DeleteVectorDocumentsByMetadataField(ctx, semanticGroupsVectorCollection, "group_id", id); err != nil {
		u.logger.Warn("semantic group pgvector delete failed", "group_id", id, "error", err)
	}
	return u.dsClient.DeleteSemanticGroup(ctx, id)
}

func (u *semanticGroupUsecase) Exists(ctx context.Context, id string) (bool, error) {
	if id == "" {
		return false, domain.NewInvalidInputError("id is required")
	}
	return u.dsClient.SemanticGroupExists(ctx, id)
}

func (u *semanticGroupUsecase) Count(ctx context.Context) (int, error) {
	return u.dsClient.SemanticGroupCount(ctx)
}

func (u *semanticGroupUsecase) AddMember(ctx context.Context, groupID string, req *domain.AddSemanticGroupMemberRequest) (*domain.SemanticGrouperTaskSubmitResult, error) {
	if u.grouper == nil {
		return nil, domain.NewInternalError(fmt.Errorf("semantic grouper client is not configured"))
	}
	groupID = strings.TrimSpace(groupID)
	if groupID == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	if _, err := u.dsClient.GetSemanticGroup(ctx, groupID); err != nil {
		return nil, err
	}
	taskID, err := u.grouper.AddMember(ctx, groupID, req)
	if err != nil {
		return nil, err
	}
	return &domain.SemanticGrouperTaskSubmitResult{TaskID: taskID}, nil
}

func (u *semanticGroupUsecase) RemoveMember(ctx context.Context, groupID string, req *domain.RemoveSemanticGroupMemberRequest) (*domain.SemanticGrouperTaskSubmitResult, error) {
	if u.grouper == nil {
		return nil, domain.NewInternalError(fmt.Errorf("semantic grouper client is not configured"))
	}
	groupID = strings.TrimSpace(groupID)
	if groupID == "" {
		return nil, domain.NewInvalidInputError("id is required")
	}
	if req == nil || strings.TrimSpace(req.SemanticDomainID) == "" {
		return nil, domain.NewInvalidInputError("sd_id is required")
	}
	if _, err := u.dsClient.GetSemanticGroup(ctx, groupID); err != nil {
		return nil, err
	}
	taskID, err := u.grouper.RemoveMember(ctx, groupID, req)
	if err != nil {
		return nil, err
	}
	return &domain.SemanticGrouperTaskSubmitResult{TaskID: taskID}, nil
}

func (u *semanticGroupUsecase) GetMemberTask(ctx context.Context, taskID string) (*domain.SemanticGrouperTaskStatus, error) {
	if u.grouper == nil {
		return nil, domain.NewInternalError(fmt.Errorf("semantic grouper client is not configured"))
	}
	taskID = strings.TrimSpace(taskID)
	if taskID == "" {
		return nil, domain.NewInvalidInputError("task_id is required")
	}
	return u.grouper.GetTaskStatus(ctx, taskID)
}
