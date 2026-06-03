package domain

import "context"

// SemanticGrouperClient submits member mutations to semantic-grouper and polls task status.
type SemanticGrouperClient interface {
	AddMember(ctx context.Context, groupID string, req *AddSemanticGroupMemberRequest) (string, error)
	RemoveMember(ctx context.Context, groupID string, req *RemoveSemanticGroupMemberRequest) (string, error)
	GetTaskStatus(ctx context.Context, taskID string) (*SemanticGrouperTaskStatus, error)
}

// AddSemanticGroupMemberRequest adds a DD to a specific semantic group.
type AddSemanticGroupMemberRequest struct {
	DDNamespace       string
	DDName            string
	AssociationReason string
}

// RemoveSemanticGroupMemberRequest removes a semantic domain from a group.
type RemoveSemanticGroupMemberRequest struct {
	SemanticDomainID string
}

// SemanticGrouperTaskSubmitResult is returned when a member mutation task is accepted.
type SemanticGrouperTaskSubmitResult struct {
	TaskID string
}

// SemanticGrouperTaskStatus mirrors semantic-grouper Celery task status.
type SemanticGrouperTaskStatus struct {
	TaskID string
	Status string
	Result map[string]any
	Error  string
}

func (s *SemanticGrouperTaskStatus) Done() bool {
	switch s.Status {
	case "SUCCESS", "FAILURE", "REVOKED":
		return true
	default:
		return false
	}
}

func (s *SemanticGrouperTaskStatus) Succeeded() bool {
	return s.Status == "SUCCESS"
}
