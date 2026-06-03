package dataservices

import (
	"context"
	"fmt"
	"strings"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// Ensure adapter implements domain.DataServicesClient at compile time.
var _ domain.DataServicesClient = (*DataServicesAdapter)(nil)

// DataServicesAdapter implements domain.DataServicesClient by delegating to *Client
// and converting between infrastructure and domain types.
type DataServicesAdapter struct {
	client *Client
}

// NewDataServicesAdapter returns a domain.DataServicesClient implemented by the HTTP client.
func NewDataServicesAdapter(client *Client) domain.DataServicesClient {
	return &DataServicesAdapter{client: client}
}

func collectionName(namespace, name string) string {
	s := fmt.Sprintf("%s_%s", namespace, name)
	return strings.ReplaceAll(s, "-", "_")
}

func toDomainSignature(s *Signature) *domain.Signature {
	if s == nil {
		return nil
	}
	return &domain.Signature{
		SigID:         s.SigID,
		SigType:       s.SigType,
		DiscoveryMode: s.DiscoveryMode,
		Fingerprint:   s.Fingerprint,
		LocationInfo:  s.LocationInfo,
		Metadata:      s.Metadata,
		DDNamespace:   s.DDNamespace,
		DDName:        s.DDName,
		CreatedAt:     s.CreatedAt,
		UpdatedAt:     s.UpdatedAt,
	}
}

func toDomainSemanticDomain(s *SemanticDomain) *domain.SemanticDomain {
	if s == nil {
		return nil
	}
	return &domain.SemanticDomain{
		SemanticDomainID: s.SemanticDomainID,
		SemanticDomain:   s.SemanticDomain,
		AgentCard:        s.AgentCard,
		DDNamespace:      s.DDNamespace,
		DDName:           s.DDName,
		CreatedAt:        s.CreatedAt,
		UpdatedAt:        s.UpdatedAt,
	}
}

func toDomainSemanticGroup(g *SemanticGroup) *domain.SemanticGroup {
	if g == nil {
		return nil
	}
	out := &domain.SemanticGroup{
		ID:          g.ID,
		GroupName:   g.GroupName,
		Description: g.Description,
		AgentCard:   g.AgentCard,
		Version:     g.Version,
		CreatedAt:   g.CreatedAt,
	}
	if g.ParentID != nil {
		out.ParentID = g.ParentID
	}
	return out
}

func toDomainDDGroupRelation(r *DDGroupRelation) *domain.DDGroupRelation {
	if r == nil {
		return nil
	}
	return &domain.DDGroupRelation{
		ID:                r.ID,
		SemanticDomainID:  r.SemanticDomainID,
		GroupID:           r.GroupID,
		AssociationReason: r.AssociationReason,
	}
}

func toDomainKnowledgeSearchResult(r KnowledgeSearchResult) domain.KnowledgeSearchResult {
	return domain.KnowledgeSearchResult{
		Content:     r.Content,
		Metadata:    r.Metadata,
		Score:       r.Score,
		SearchType:  r.SearchType,
		HybridScore: r.HybridScore,
	}
}

func toDomainKnowledgeDocument(d KnowledgeDocument) domain.KnowledgeDocument {
	return domain.KnowledgeDocument{
		PageContent: d.PageContent,
		Vector:      d.Vector,
		Metadata:    d.Metadata,
		Provider:    d.Provider,
		Children:    d.Children,
	}
}

func toDomainMessageItem(m HistoryMessage) domain.MessageItem {
	return domain.MessageItem{
		Role:    m.Role,
		Content: m.Content,
		Think:   m.Think,
	}
}

func toDomainHistoryRecord(h HistoryRecord) domain.HistoryRecord {
	msgs := make([]domain.MessageItem, len(h.Messages))
	for i := range h.Messages {
		msgs[i] = toDomainMessageItem(h.Messages[i])
	}
	return domain.HistoryRecord{
		HID:       h.HID,
		UserID:    h.UserID,
		AgentID:   h.AgentID,
		RunID:     h.RunID,
		Messages:  msgs,
		CreatedAt: h.CreatedAt,
		UpdatedAt: h.UpdatedAt,
	}
}

// GetRunHistory implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetRunHistory(ctx context.Context, userID, runID string) ([]domain.HistoryRecord, error) {
	return a.mapRunHistory(a.client.GetRunHistory(ctx, userID, runID))
}

// GetRunHistoryForTitle implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetRunHistoryForTitle(ctx context.Context, userID, runID string) ([]domain.HistoryRecord, error) {
	return a.mapRunHistory(a.client.GetRunHistoryForTitle(ctx, userID, runID))
}

func (a *DataServicesAdapter) mapRunHistory(list []HistoryRecord, err error) ([]domain.HistoryRecord, error) {
	if err != nil {
		return nil, err
	}
	out := make([]domain.HistoryRecord, len(list))
	for i := range list {
		out[i] = toDomainHistoryRecord(list[i])
	}
	return out, nil
}

// GetSignatureByDD implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetSignatureByDD(ctx context.Context, namespace, name string) (*domain.Signature, error) {
	s, err := a.client.GetSignatureByDD(ctx, namespace, name)
	if err != nil {
		return nil, err
	}
	return toDomainSignature(s), nil
}

// GetSemanticDomainByDD implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetSemanticDomainByDD(ctx context.Context, namespace, name string) (*domain.SemanticDomain, error) {
	s, err := a.client.GetSemanticDomainByDD(ctx, namespace, name)
	if err != nil {
		return nil, err
	}
	return toDomainSemanticDomain(s), nil
}

// SearchKnowledge implements domain.DataServicesClient.
func (a *DataServicesAdapter) SearchKnowledge(ctx context.Context, namespace, name, query string) ([]domain.KnowledgeSearchResult, error) {
	col := collectionName(namespace, name)
	list, err := a.client.SearchKnowledge(ctx, col, query, 100)
	if err != nil {
		return nil, err
	}
	out := make([]domain.KnowledgeSearchResult, len(list))
	for i := range list {
		out[i] = toDomainKnowledgeSearchResult(list[i])
	}
	return out, nil
}

// GetAllKnowledge implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetAllKnowledge(ctx context.Context, namespace, name string) ([]domain.KnowledgeDocument, error) {
	col := collectionName(namespace, name)
	list, err := a.client.GetAllKnowledge(ctx, col)
	if err != nil {
		return nil, err
	}
	out := make([]domain.KnowledgeDocument, len(list))
	for i := range list {
		out[i] = toDomainKnowledgeDocument(list[i])
	}
	return out, nil
}

// DeleteKnowledge implements domain.DataServicesClient.
func (a *DataServicesAdapter) DeleteKnowledge(ctx context.Context, namespace, name string, docIDs []string) error {
	col := collectionName(namespace, name)
	return a.client.DeleteKnowledge(ctx, col, docIDs)
}

// CreateSemanticGroup implements domain.DataServicesClient.
func (a *DataServicesAdapter) CreateSemanticGroup(ctx context.Context, req map[string]any) (*domain.SemanticGroup, error) {
	g, err := a.client.CreateSemanticGroup(ctx, req)
	if err != nil {
		return nil, err
	}
	return toDomainSemanticGroup(g), nil
}

// BatchCreateSemanticGroups implements domain.DataServicesClient.
func (a *DataServicesAdapter) BatchCreateSemanticGroups(ctx context.Context, req []map[string]any) (int, error) {
	return a.client.BatchCreateSemanticGroups(ctx, req)
}

// GetSemanticGroup implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetSemanticGroup(ctx context.Context, id string) (*domain.SemanticGroup, error) {
	g, err := a.client.GetSemanticGroup(ctx, id)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return nil, domain.NewNotFoundError("semantic group", id)
		}
		return nil, err
	}
	return toDomainSemanticGroup(g), nil
}

// GetSemanticGroupWithMembers implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetSemanticGroupWithMembers(ctx context.Context, id string) (*domain.SemanticGroupWithMembers, error) {
	data, err := a.client.GetSemanticGroupWithMembers(ctx, id)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return nil, domain.NewNotFoundError("semantic group", id)
		}
		return nil, fmt.Errorf("get semantic group with members: %w", err)
	}
	out := &domain.SemanticGroupWithMembers{
		Group:       *toDomainSemanticGroup(&data.Group),
		Members:     make([]domain.SemanticGroupMemberDetail, len(data.Members)),
		ChildGroups: make([]domain.SemanticGroupInfo, len(data.ChildGroups)),
	}
	for i := range data.Members {
		m := &data.Members[i]
		out.Members[i] = domain.SemanticGroupMemberDetail{
			Relation: domain.DDGroupRelation{
				ID:                m.Relation.ID,
				SemanticDomainID:  m.Relation.SemanticDomainID,
				GroupID:           m.Relation.GroupID,
				AssociationReason: m.Relation.AssociationReason,
			},
			SemanticDomain: toDomainSemanticDomain(m.SemanticDomain),
		}
	}
	for i := range data.ChildGroups {
		c := &data.ChildGroups[i]
		out.ChildGroups[i] = domain.SemanticGroupInfo{
			ID:          c.ID,
			GroupName:   c.GroupName,
			Description: c.Description,
			AgentCard:   c.AgentCard,
		}
	}
	return out, nil
}

// ListSemanticGroups implements domain.DataServicesClient.
func (a *DataServicesAdapter) ListSemanticGroups(ctx context.Context, page, pageSize int) ([]domain.SemanticGroup, int, error) {
	list, total, err := a.client.ListSemanticGroups(ctx, page, pageSize)
	if err != nil {
		return nil, 0, err
	}
	out := make([]domain.SemanticGroup, len(list))
	for i := range list {
		out[i] = *toDomainSemanticGroup(&list[i])
	}
	return out, total, nil
}

// UpdateSemanticGroup implements domain.DataServicesClient.
func (a *DataServicesAdapter) UpdateSemanticGroup(ctx context.Context, id string, req map[string]any) (*domain.SemanticGroup, error) {
	g, err := a.client.UpdateSemanticGroup(ctx, id, req)
	if err != nil {
		return nil, err
	}
	return toDomainSemanticGroup(g), nil
}

// DeleteSemanticGroup implements domain.DataServicesClient.
func (a *DataServicesAdapter) DeleteSemanticGroup(ctx context.Context, id string) error {
	err := a.client.DeleteSemanticGroup(ctx, id)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return domain.NewNotFoundError("semantic group", id)
		}
		return err
	}
	return nil
}

// SemanticGroupExists implements domain.DataServicesClient.
func (a *DataServicesAdapter) SemanticGroupExists(ctx context.Context, id string) (bool, error) {
	exists, err := a.client.SemanticGroupExists(ctx, id)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return false, nil
		}
		return false, err
	}
	return exists, nil
}

// SemanticGroupCount implements domain.DataServicesClient.
func (a *DataServicesAdapter) SemanticGroupCount(ctx context.Context) (int, error) {
	return a.client.SemanticGroupCount(ctx)
}

// ListSemanticGroupRoots implements domain.DataServicesClient.
func (a *DataServicesAdapter) ListSemanticGroupRoots(ctx context.Context) ([]domain.SemanticGroup, int, error) {
	list, total, err := a.client.ListSemanticGroupRoots(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("list semantic group roots: %w", err)
	}
	out := make([]domain.SemanticGroup, len(list))
	for i := range list {
		out[i] = *toDomainSemanticGroup(&list[i])
	}
	return out, total, nil
}

// ListDDGroupRelationsByGroup implements domain.DataServicesClient.
func (a *DataServicesAdapter) ListDDGroupRelationsByGroup(ctx context.Context, groupID string) ([]domain.DDGroupRelation, int, error) {
	list, total, err := a.client.ListDDGroupRelationsByGroup(ctx, groupID)
	if err != nil {
		return nil, 0, err
	}
	out := make([]domain.DDGroupRelation, len(list))
	for i := range list {
		out[i] = *toDomainDDGroupRelation(&list[i])
	}
	return out, total, nil
}

// ListDDGroupRelationsBySD implements domain.DataServicesClient.
func (a *DataServicesAdapter) ListDDGroupRelationsBySD(ctx context.Context, sdID string) ([]domain.DDGroupRelation, int, error) {
	list, total, err := a.client.ListDDGroupRelationsBySD(ctx, sdID)
	if err != nil {
		return nil, 0, err
	}
	out := make([]domain.DDGroupRelation, len(list))
	for i := range list {
		out[i] = *toDomainDDGroupRelation(&list[i])
	}
	return out, total, nil
}

// DeleteDDGroupRelationByID implements domain.DataServicesClient.
func (a *DataServicesAdapter) DeleteDDGroupRelationByID(ctx context.Context, id int64) error {
	return a.client.DeleteDDGroupRelationByID(ctx, id)
}

// GetSemanticDomain implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetSemanticDomain(ctx context.Context, id string) (*domain.SemanticDomain, error) {
	s, err := a.client.GetSemanticDomain(ctx, id)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return nil, domain.NewNotFoundError("semantic domain", id)
		}
		return nil, err
	}
	return toDomainSemanticDomain(s), nil
}

// CreateSemanticDomain implements domain.DataServicesClient.
func (a *DataServicesAdapter) CreateSemanticDomain(ctx context.Context, req map[string]any) (*domain.SemanticDomain, error) {
	s, err := a.client.CreateSemanticDomain(ctx, req)
	if err != nil {
		return nil, err
	}
	return toDomainSemanticDomain(s), nil
}

// BatchCreateSemanticDomains implements domain.DataServicesClient.
func (a *DataServicesAdapter) BatchCreateSemanticDomains(ctx context.Context, req []map[string]any) (int, error) {
	return a.client.BatchCreateSemanticDomains(ctx, req)
}

// SearchSemanticDomainsByDD implements domain.DataServicesClient.
func (a *DataServicesAdapter) SearchSemanticDomainsByDD(ctx context.Context, namespace, name string) ([]domain.SemanticDomain, int, error) {
	list, total, err := a.client.SearchSemanticDomainsByDD(ctx, namespace, name)
	if err != nil {
		return nil, 0, err
	}
	out := make([]domain.SemanticDomain, len(list))
	for i := range list {
		out[i] = *toDomainSemanticDomain(&list[i])
	}
	return out, total, nil
}

// UpdateSemanticDomain implements domain.DataServicesClient.
func (a *DataServicesAdapter) UpdateSemanticDomain(ctx context.Context, id string, req map[string]any) (*domain.SemanticDomain, error) {
	s, err := a.client.UpdateSemanticDomain(ctx, id, req)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return nil, domain.NewNotFoundError("semantic domain", id)
		}
		return nil, err
	}
	return toDomainSemanticDomain(s), nil
}

// DeleteSemanticDomain implements domain.DataServicesClient.
func (a *DataServicesAdapter) DeleteSemanticDomain(ctx context.Context, id string) error {
	err := a.client.DeleteSemanticDomain(ctx, id)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return domain.NewNotFoundError("semantic domain", id)
		}
		return err
	}
	return nil
}

// DeleteSemanticDomainByDDInfo implements domain.DataServicesClient.
func (a *DataServicesAdapter) DeleteSemanticDomainByDDInfo(ctx context.Context, ddNamespace, ddName string) error {
	return a.client.DeleteSemanticDomainByDDInfo(ctx, ddNamespace, ddName)
}

// SemanticDomainExists implements domain.DataServicesClient.
func (a *DataServicesAdapter) SemanticDomainExists(ctx context.Context, id string) (bool, error) {
	exists, err := a.client.SemanticDomainExists(ctx, id)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return false, nil
		}
		return false, err
	}
	return exists, nil
}

// SemanticDomainExistsByDDInfo implements domain.DataServicesClient.
func (a *DataServicesAdapter) SemanticDomainExistsByDDInfo(ctx context.Context, ddNamespace, ddName string) (bool, error) {
	exists, err := a.client.SemanticDomainExistsByDDInfo(ctx, ddNamespace, ddName)
	if err != nil {
		if he, ok := err.(*HTTPError); ok && he.StatusCode == 404 {
			return false, nil
		}
		return false, err
	}
	return exists, nil
}

// SemanticDomainCount implements domain.DataServicesClient.
func (a *DataServicesAdapter) SemanticDomainCount(ctx context.Context) (int, error) {
	return a.client.SemanticDomainCount(ctx)
}

// KnowledgeGraphAddWithSource implements domain.DataServicesClient.
func (a *DataServicesAdapter) KnowledgeGraphAddWithSource(ctx context.Context, req map[string]any) (map[string]any, error) {
	return a.client.KnowledgeGraphAddWithSource(ctx, req)
}

// KnowledgeGraphSearchWithSource implements domain.DataServicesClient.
func (a *DataServicesAdapter) KnowledgeGraphSearchWithSource(ctx context.Context, req map[string]any) (map[string]any, error) {
	return a.client.KnowledgeGraphSearchWithSource(ctx, req)
}

// KnowledgeGraphGetGraphBySource implements domain.DataServicesClient.
func (a *DataServicesAdapter) KnowledgeGraphGetGraphBySource(ctx context.Context, req map[string]any) (map[string]any, error) {
	return a.client.KnowledgeGraphGetGraphBySource(ctx, req)
}

// KnowledgeGraphDeleteWithSource implements domain.DataServicesClient.
func (a *DataServicesAdapter) KnowledgeGraphDeleteWithSource(ctx context.Context, req map[string]any) (map[string]any, error) {
	return a.client.KnowledgeGraphDeleteWithSource(ctx, req)
}

// DeleteVectorDocumentsByMetadataField implements domain.DataServicesClient.
func (a *DataServicesAdapter) DeleteVectorDocumentsByMetadataField(ctx context.Context, collectionName, key, value string) error {
	return a.client.DeleteVectorByMetadataField(ctx, collectionName, key, value)
}

// GetVectorDocumentIDsByMetadataField implements domain.DataServicesClient.
func (a *DataServicesAdapter) GetVectorDocumentIDsByMetadataField(ctx context.Context, collectionName, key, value string) ([]string, error) {
	return a.client.GetVectorDocumentIDsByMetadataField(ctx, collectionName, key, value)
}

// DeleteVectorDocumentsByIDs implements domain.DataServicesClient.
func (a *DataServicesAdapter) DeleteVectorDocumentsByIDs(ctx context.Context, collectionName string, documentIDs []string) error {
	return a.client.DeleteVectorDocumentsByIDs(ctx, collectionName, documentIDs)
}

// AddVectorDocuments implements domain.DataServicesClient.
func (a *DataServicesAdapter) AddVectorDocuments(ctx context.Context, collectionName string, documents []domain.VectorDocumentInput) error {
	if len(documents) == 0 {
		return nil
	}
	infraDocs := make([]VectorDocument, len(documents))
	for i, doc := range documents {
		infraDocs[i] = VectorDocument{
			PageContent: doc.PageContent,
			Metadata:    doc.Metadata,
		}
	}
	return a.client.AddVectorDocuments(ctx, collectionName, infraDocs)
}
