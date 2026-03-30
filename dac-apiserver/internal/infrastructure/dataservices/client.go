package dataservices

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"

	"github.com/bytedance/sonic"
)

// Client is a small HTTP client for DAC data-services.
// It intentionally keeps a narrow surface area: only the endpoints used by dac-apiserver.
type Client struct {
	baseURL string
	http    *http.Client
	logger  *slog.Logger
}

func NewClient(baseURL string, timeout time.Duration, logger *slog.Logger) *Client {
	if logger == nil {
		logger = slog.Default()
	}
	baseURL = strings.TrimRight(strings.TrimSpace(baseURL), "/")
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	return &Client{
		baseURL: baseURL,
		http:    &http.Client{Timeout: timeout},
		logger:  logger,
	}
}

func (c *Client) buildURL(p string) (string, error) {
	if c.baseURL == "" {
		return "", fmt.Errorf("data services baseURL is empty")
	}
	u, err := url.Parse(c.baseURL)
	if err != nil {
		return "", fmt.Errorf("invalid data services baseURL: %w", err)
	}
	u.Path = path.Join(u.Path, p)
	return u.String(), nil
}

func (c *Client) doJSON(ctx context.Context, method, urlStr string, body any, out any) error {
	var r io.Reader
	if body != nil {
		b, err := sonic.Marshal(body)
		if err != nil {
			return fmt.Errorf("marshal request: %w", err)
		}
		r = bytes.NewReader(b)
	}

	req, err := http.NewRequestWithContext(ctx, method, urlStr, r)
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	bs, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return &HTTPError{StatusCode: resp.StatusCode, Body: strings.TrimSpace(string(bs))}
	}
	if out == nil {
		return nil
	}
	if err := sonic.Unmarshal(bs, out); err != nil {
		return fmt.Errorf("unmarshal response: %w", err)
	}
	return nil
}

// --- Knowledge Graph ---

// doKnowledgeGraph calls a knowledge_graph sub-path with the given method and request,
// then normalises the response (nil Data, _message, _status) for UI use.
func (c *Client) doKnowledgeGraph(ctx context.Context, pathSuffix, method string, req map[string]any) (map[string]any, error) {
	u, err := c.buildURL("/knowledge_graph/" + pathSuffix)
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status  string         `json:"status"`
		Message string         `json:"message"`
		Data    map[string]any `json:"data"`
	}
	if err := c.doJSON(ctx, method, u, req, &resp); err != nil {
		return nil, err
	}
	if resp.Data == nil {
		resp.Data = map[string]any{}
	}
	resp.Data["_message"] = resp.Message
	resp.Data["_status"] = resp.Status
	return resp.Data, nil
}

// KnowledgeGraphAddWithSource proxies /knowledge_graph/add_with_source.
func (c *Client) KnowledgeGraphAddWithSource(ctx context.Context, req map[string]any) (map[string]any, error) {
	return c.doKnowledgeGraph(ctx, "add_with_source", http.MethodPost, req)
}

// KnowledgeGraphSearchWithSource proxies /knowledge_graph/search_with_source.
func (c *Client) KnowledgeGraphSearchWithSource(ctx context.Context, req map[string]any) (map[string]any, error) {
	return c.doKnowledgeGraph(ctx, "search_with_source", http.MethodPost, req)
}

// KnowledgeGraphGetGraphBySource proxies /knowledge_graph/get_graph_by_source.
func (c *Client) KnowledgeGraphGetGraphBySource(ctx context.Context, req map[string]any) (map[string]any, error) {
	return c.doKnowledgeGraph(ctx, "get_graph_by_source", http.MethodPost, req)
}

// KnowledgeGraphDeleteWithSource proxies /knowledge_graph/delete_with_source.
func (c *Client) KnowledgeGraphDeleteWithSource(ctx context.Context, req map[string]any) (map[string]any, error) {
	return c.doKnowledgeGraph(ctx, "delete_with_source", http.MethodDelete, req)
}

// --- Semantic Groups ---

// CreateSemanticGroup creates a semantic group.
func (c *Client) CreateSemanticGroup(ctx context.Context, req map[string]any) (*SemanticGroup, error) {
	u, err := c.buildURL("/semantic_groups")
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string        `json:"status"`
		Data   SemanticGroup `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// BatchCreateSemanticGroups batch creates semantic groups.
func (c *Client) BatchCreateSemanticGroups(ctx context.Context, req []map[string]any) (int, error) {
	u, err := c.buildURL("/semantic_groups/batch")
	if err != nil {
		return 0, err
	}
	var resp struct {
		Status string `json:"status"`
		Data   struct {
			Count int `json:"count"`
		} `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return 0, err
	}
	return resp.Data.Count, nil
}

// GetSemanticGroup gets a semantic group by id.
func (c *Client) GetSemanticGroup(ctx context.Context, id string) (*SemanticGroup, error) {
	u, err := c.buildURL("/semantic_groups/" + url.PathEscape(id))
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string        `json:"status"`
		Data   SemanticGroup `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// ListSemanticGroups lists semantic groups with pagination (page/page_size).
func (c *Client) ListSemanticGroups(ctx context.Context, page, pageSize int) ([]SemanticGroup, int, error) {
	if page <= 0 {
		page = 1
	}
	if pageSize <= 0 {
		pageSize = 50
	}
	u, err := c.buildURL("/semantic_groups")
	if err != nil {
		return nil, 0, err
	}
	uu, err := url.Parse(u)
	if err != nil {
		return nil, 0, fmt.Errorf("parse url: %w", err)
	}
	q := uu.Query()
	q.Set("page", fmt.Sprintf("%d", page))
	q.Set("page_size", fmt.Sprintf("%d", pageSize))
	uu.RawQuery = q.Encode()

	var resp struct {
		Status string          `json:"status"`
		Data   []SemanticGroup `json:"data"`
		Count  int             `json:"count"`
	}
	if err := c.doJSON(ctx, http.MethodGet, uu.String(), nil, &resp); err != nil {
		return nil, 0, err
	}
	return resp.Data, resp.Count, nil
}

// UpdateSemanticGroup updates a semantic group.
func (c *Client) UpdateSemanticGroup(ctx context.Context, id string, req map[string]any) (*SemanticGroup, error) {
	u, err := c.buildURL("/semantic_groups/" + url.PathEscape(id))
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string        `json:"status"`
		Data   SemanticGroup `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodPut, u, req, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// DeleteSemanticGroup deletes a semantic group.
func (c *Client) DeleteSemanticGroup(ctx context.Context, id string) error {
	u, err := c.buildURL("/semantic_groups/" + url.PathEscape(id))
	if err != nil {
		return err
	}
	return c.doJSON(ctx, http.MethodDelete, u, nil, nil)
}

// SemanticGroupExists checks existence by group id.
func (c *Client) SemanticGroupExists(ctx context.Context, id string) (bool, error) {
	u, err := c.buildURL("/semantic_groups/" + url.PathEscape(id) + "/exists")
	if err != nil {
		return false, err
	}
	var resp struct {
		Status string `json:"status"`
		Data   struct {
			Exists bool `json:"exists"`
		} `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return false, err
	}
	return resp.Data.Exists, nil
}

// SemanticGroupCount returns total_count.
func (c *Client) SemanticGroupCount(ctx context.Context) (int, error) {
	u, err := c.buildURL("/semantic_groups/status/count")
	if err != nil {
		return 0, err
	}
	var resp struct {
		Status string `json:"status"`
		Data   struct {
			TotalCount int `json:"total_count"`
		} `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return 0, err
	}
	return resp.Data.TotalCount, nil
}

// GetSemanticGroupWithMembers returns the group plus its member semantic domains (via dd_group_relations) and child groups.
// Uses GET /semantic_groups/:id/with_members so root groups show members correctly.
func (c *Client) GetSemanticGroupWithMembers(ctx context.Context, id string) (*SemanticGroupWithMembersData, error) {
	u, err := c.buildURL("/semantic_groups/" + url.PathEscape(id) + "/with_members")
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string                      `json:"status"`
		Data   SemanticGroupWithMembersData `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// ListSemanticGroupRoots returns all root groups (parent_id IS NULL).
func (c *Client) ListSemanticGroupRoots(ctx context.Context) ([]SemanticGroup, int, error) {
	u, err := c.buildURL("/semantic_groups_roots")
	if err != nil {
		return nil, 0, err
	}
	var resp struct {
		Status string          `json:"status"`
		Data   []SemanticGroup `json:"data"`
		Count  int             `json:"count"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return nil, 0, err
	}
	return resp.Data, resp.Count, nil
}

// --- DD Group Relations ---

// CreateDDGroupRelation creates a relation between semantic domain and group.
func (c *Client) CreateDDGroupRelation(ctx context.Context, req map[string]any) (*DDGroupRelation, error) {
	u, err := c.buildURL("/dd_group_relations")
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string          `json:"status"`
		Data   DDGroupRelation `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// BatchCreateDDGroupRelations batch creates relations.
func (c *Client) BatchCreateDDGroupRelations(ctx context.Context, req []map[string]any) (int, error) {
	u, err := c.buildURL("/dd_group_relations/batch")
	if err != nil {
		return 0, err
	}
	var resp struct {
		Status string `json:"status"`
		Data   struct {
			Count int `json:"count"`
		} `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return 0, err
	}
	return resp.Data.Count, nil
}

func (c *Client) ListDDGroupRelationsByGroup(ctx context.Context, groupID string) ([]DDGroupRelation, int, error) {
	u, err := c.buildURL("/dd_group_relations/group/" + url.PathEscape(groupID))
	if err != nil {
		return nil, 0, err
	}
	var resp struct {
		Status string            `json:"status"`
		Data   []DDGroupRelation `json:"data"`
		Count  int               `json:"count"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return nil, 0, err
	}
	return resp.Data, resp.Count, nil
}

func (c *Client) ListDDGroupRelationsBySD(ctx context.Context, sdID string) ([]DDGroupRelation, int, error) {
	u, err := c.buildURL("/dd_group_relations/sd/" + url.PathEscape(sdID))
	if err != nil {
		return nil, 0, err
	}
	var resp struct {
		Status string            `json:"status"`
		Data   []DDGroupRelation `json:"data"`
		Count  int               `json:"count"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return nil, 0, err
	}
	return resp.Data, resp.Count, nil
}

func (c *Client) DeleteDDGroupRelationByID(ctx context.Context, id int64) error {
	u, err := c.buildURL(fmt.Sprintf("/dd_group_relations/%d", id))
	if err != nil {
		return err
	}
	return c.doJSON(ctx, http.MethodDelete, u, nil, nil)
}

func (c *Client) DeleteDDGroupRelationsByGroup(ctx context.Context, groupID string) error {
	u, err := c.buildURL("/dd_group_relations/group/" + url.PathEscape(groupID))
	if err != nil {
		return err
	}
	return c.doJSON(ctx, http.MethodDelete, u, nil, nil)
}

func (c *Client) DeleteDDGroupRelationsBySD(ctx context.Context, sdID string) error {
	u, err := c.buildURL("/dd_group_relations/sd/" + url.PathEscape(sdID))
	if err != nil {
		return err
	}
	return c.doJSON(ctx, http.MethodDelete, u, nil, nil)
}

// GetRunHistory loads conversation history records for a run.
// Uses /history/search_user_run so we can retrieve the whole run without pinning agent_id.
func (c *Client) GetRunHistory(ctx context.Context, userID, runID string) ([]HistoryRecord, error) {
	u, err := c.buildURL("/history/search_user_run")
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status  string          `json:"status"`
		Data    []HistoryRecord `json:"data"`
		Total   int             `json:"total"`
		Message string          `json:"message"`
	}
	req := map[string]any{
		"user_id": userID,
		"run_id":  runID,
		"limit":   1000,
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return nil, err
	}
	return resp.Data, nil
}

// GetSignatureByDD gets the newest signature record for a given dd (namespace/name), if any.
func (c *Client) GetSignatureByDD(ctx context.Context, namespace, name string) (*Signature, error) {
	u, err := c.buildURL("/signatures/search/by-dd")
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string      `json:"status"`
		Data   []Signature `json:"data"`
		Count  int         `json:"count"`
	}
	req := map[string]any{
		"dd_namespace": namespace,
		"dd_name":      name,
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return nil, err
	}
	if len(resp.Data) == 0 {
		return nil, nil
	}
	return &resp.Data[0], nil
}

// GetSemanticDomainByDD gets the newest semantic_domain record for a given dd (namespace/name), if any.
func (c *Client) GetSemanticDomainByDD(ctx context.Context, namespace, name string) (*SemanticDomain, error) {
	items, _, err := c.SearchSemanticDomainsByDD(ctx, namespace, name)
	if err != nil {
		return nil, err
	}
	if len(items) == 0 {
		return nil, nil
	}
	return &items[0], nil
}

// GetSemanticDomain gets a semantic domain by semantic_domain_id.
func (c *Client) GetSemanticDomain(ctx context.Context, id string) (*SemanticDomain, error) {
	u, err := c.buildURL("/semantic_domains/" + url.PathEscape(id))
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string         `json:"status"`
		Data   SemanticDomain `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

// --- Semantic Domains ---

func (c *Client) CreateSemanticDomain(ctx context.Context, req map[string]any) (*SemanticDomain, error) {
	u, err := c.buildURL("/semantic_domains")
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string         `json:"status"`
		Data   SemanticDomain `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

func (c *Client) BatchCreateSemanticDomains(ctx context.Context, req []map[string]any) (int, error) {
	u, err := c.buildURL("/semantic_domains/batch")
	if err != nil {
		return 0, err
	}
	var resp struct {
		Status string `json:"status"`
		Data   struct {
			Count int `json:"count"`
		} `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return 0, err
	}
	return resp.Data.Count, nil
}

func (c *Client) SearchSemanticDomainsByDD(ctx context.Context, namespace, name string) ([]SemanticDomain, int, error) {
	u, err := c.buildURL("/semantic_domains/search/by-dd")
	if err != nil {
		return nil, 0, err
	}
	var resp struct {
		Status string           `json:"status"`
		Data   []SemanticDomain `json:"data"`
		Count  int              `json:"count"`
	}
	req := map[string]any{
		"dd_namespace": namespace,
		"dd_name":      name,
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return nil, 0, err
	}
	return resp.Data, resp.Count, nil
}

func (c *Client) UpdateSemanticDomain(ctx context.Context, id string, req map[string]any) (*SemanticDomain, error) {
	u, err := c.buildURL("/semantic_domains/" + url.PathEscape(id))
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status string         `json:"status"`
		Data   SemanticDomain `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodPut, u, req, &resp); err != nil {
		return nil, err
	}
	return &resp.Data, nil
}

func (c *Client) DeleteSemanticDomain(ctx context.Context, id string) error {
	u, err := c.buildURL("/semantic_domains/" + url.PathEscape(id))
	if err != nil {
		return err
	}
	return c.doJSON(ctx, http.MethodDelete, u, nil, nil)
}

func (c *Client) DeleteSemanticDomainByDDInfo(ctx context.Context, ddNamespace, ddName string) error {
	u, err := c.buildURL("/semantic_domains/dd_info/" + url.PathEscape(ddNamespace) + "/" + url.PathEscape(ddName))
	if err != nil {
		return err
	}
	return c.doJSON(ctx, http.MethodDelete, u, nil, nil)
}

func (c *Client) SemanticDomainExists(ctx context.Context, id string) (bool, error) {
	u, err := c.buildURL("/semantic_domains/" + url.PathEscape(id) + "/exists")
	if err != nil {
		return false, err
	}
	var resp struct {
		Status string `json:"status"`
		Data   struct {
			Exists bool `json:"exists"`
		} `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return false, err
	}
	return resp.Data.Exists, nil
}

func (c *Client) SemanticDomainExistsByDDInfo(ctx context.Context, ddNamespace, ddName string) (bool, error) {
	u, err := c.buildURL("/semantic_domains/dd_info/" + url.PathEscape(ddNamespace) + "/" + url.PathEscape(ddName) + "/exists")
	if err != nil {
		return false, err
	}
	var resp struct {
		Status string `json:"status"`
		Data   struct {
			Exists bool `json:"exists"`
		} `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return false, err
	}
	return resp.Data.Exists, nil
}

func (c *Client) SemanticDomainCount(ctx context.Context) (int, error) {
	u, err := c.buildURL("/semantic_domains/status/count")
	if err != nil {
		return 0, err
	}
	var resp struct {
		Status string `json:"status"`
		Data   struct {
			TotalCount int `json:"total_count"`
		} `json:"data"`
	}
	if err := c.doJSON(ctx, http.MethodGet, u, nil, &resp); err != nil {
		return 0, err
	}
	return resp.Data.TotalCount, nil
}

// SearchKnowledge searches knowledge pyramid in a collection.
// GetAllKnowledge retrieves all knowledge documents from a collection.
func (c *Client) GetAllKnowledge(ctx context.Context, collection string) ([]KnowledgeDocument, error) {
	u, err := c.buildURL(fmt.Sprintf("/knowledge_pyramid/%s/get_all", url.PathEscape(collection)))
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status       string             `json:"status"`
		Collection   string             `json:"collection"`
		VectorResult []KnowledgeDocument `json:"vector_result"`
		Message      string             `json:"message"`
	}
	req := map[string]any{}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return nil, err
	}
	return resp.VectorResult, nil
}

// SearchKnowledge searches for knowledge in a collection.
func (c *Client) SearchKnowledge(ctx context.Context, collection, query string, limit int) ([]KnowledgeSearchResult, error) {
	if limit <= 0 {
		limit = 10
	}
	u, err := c.buildURL(fmt.Sprintf("/knowledge_pyramid/%s/search", url.PathEscape(collection)))
	if err != nil {
		return nil, err
	}
	var resp struct {
		Status        string                  `json:"status"`
		Collection    string                  `json:"collection"`
		SearchType    string                  `json:"search_type"`
		VectorResult  []KnowledgeSearchResult `json:"vector_result"`
		VectorResults []KnowledgeSearchResult `json:"vector_results"`
		Message       string                  `json:"message"`
	}
	req := map[string]any{
		"query":       query,
		"search_type": "vector",
		"limit":       limit,
	}
	if err := c.doJSON(ctx, http.MethodPost, u, req, &resp); err != nil {
		return nil, err
	}
	if len(resp.VectorResult) > 0 {
		return resp.VectorResult, nil
	}
	return resp.VectorResults, nil
}

// DeleteKnowledge deletes knowledge documents by IDs in a collection.
func (c *Client) DeleteKnowledge(ctx context.Context, collection string, docIDs []string) error {
	u, err := c.buildURL(fmt.Sprintf("/knowledge_pyramid/%s/delete_by_ids", url.PathEscape(collection)))
	if err != nil {
		return err
	}
	req := map[string]any{"documents": docIDs}
	return c.doJSON(ctx, http.MethodDelete, u, req, nil)
}
