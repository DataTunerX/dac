package http

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type KnowledgePyramidCreateCollectionRequest struct {
	CollectionName string                     `json:"collection_name"`
	Documents      []KnowledgePyramidDocument `json:"documents"`
}

type KnowledgePyramidDocument struct {
	PageContent string                 `json:"page_content"`
	Metadata    map[string]interface{} `json:"metadata"`
}

type KnowledgePyramidCreateCollectionResponse struct {
	Status  string `json:"status"`
	Message string `json:"message"`
}

type KnowledgePyramidDeleteCollectionRequest struct {
	CollectionName string `json:"collection_name"`
}

type KnowledgePyramidDeleteCollectionResponse struct {
	Status  string `json:"status"`
	Message string `json:"message"`
}

type FingerprintSearchByDDRequest struct {
	DdNamespace string `json:"dd_namespace"`
	DdName      string `json:"dd_name"`
}

type Fingerprint struct {
	FID                string `json:"fid"`
	FingerprintID      string `json:"fingerprint_id"`
	FingerprintSummary string `json:"fingerprint_summary"`
	SemanticDomain     string `json:"semantic_domain"`
	AgentCard          string `json:"agent_card"`
	DdNamespace        string `json:"dd_namespace"`
	DdName             string `json:"dd_name"`
}

type FingerprintListResponse struct {
	Status string        `json:"status"`
	Data   []Fingerprint `json:"data"`
	Count  int           `json:"count"`
}

// KnowledgePyramidCreateCollection
func (c *APIClient) KnowledgePyramidCreateCollection(ctx context.Context, req *KnowledgePyramidCreateCollectionRequest) (*KnowledgePyramidCreateCollectionResponse, error) {
	jsonData, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal create collection request failed: %v", err)
	}

	httpReq, err := http.NewRequestWithContext(
		ctx,
		"POST",
		c.cfg.DataServicesBaseURL+createCollection,
		bytes.NewBuffer(jsonData),
	)
	if err != nil {
		return nil, fmt.Errorf("create http request failed: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.doRequestWithRetry(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("unexpected status code: %d, response: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response failed: %v", err)
	}

	var response KnowledgePyramidCreateCollectionResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %v", err)
	}

	return &response, nil
}

// KnowledgePyramidDeleteCollection
func (c *APIClient) KnowledgePyramidDeleteCollection(ctx context.Context, req *KnowledgePyramidDeleteCollectionRequest) (*KnowledgePyramidDeleteCollectionResponse, error) {
	jsonData, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal delete collection request failed: %v", err)
	}

	httpReq, err := http.NewRequestWithContext(
		ctx,
		"DELETE",
		c.cfg.DataServicesBaseURL+deleteCollection,
		bytes.NewBuffer(jsonData),
	)
	if err != nil {
		return nil, fmt.Errorf("create http request failed: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.doRequestWithRetry(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("unexpected status code: %d, response: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response failed: %v", err)
	}

	var response KnowledgePyramidDeleteCollectionResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %v", err)
	}

	return &response, nil
}

// ─── Semantic Domain ─────────────────────────────────────────────────────────

type SemanticDomainSearchByDDRequest struct {
	DdNamespace string `json:"dd_namespace"`
	DdName      string `json:"dd_name"`
}

type SemanticDomainRecord struct {
	SemanticDomainID string `json:"semantic_domain_id"`
	SemanticDomain   string `json:"semantic_domain"`
	AgentCard        string `json:"agent_card"`
	DdNamespace      string `json:"dd_namespace"`
	DdName           string `json:"dd_name"`
	DescriptorType   string `json:"descriptor_type"`
}

type SemanticDomainListResponse struct {
	Status string                 `json:"status"`
	Data   []SemanticDomainRecord `json:"data"`
	Count  int                    `json:"count"`
}

// SemanticDomainSearchByDD queries semantic domains by DataDescriptor namespace and name.
// POST /semantic_domains/search/by-dd
func (c *APIClient) SemanticDomainSearchByDD(ctx context.Context, req *SemanticDomainSearchByDDRequest) (*SemanticDomainListResponse, error) {
	if req.DdNamespace == "" || req.DdName == "" {
		return nil, fmt.Errorf("both dd_namespace and dd_name are required")
	}

	jsonData, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal search request failed: %v", err)
	}

	httpReq, err := http.NewRequestWithContext(
		ctx,
		"POST",
		c.cfg.DataServicesBaseURL+"/semantic_domains/search/by-dd",
		bytes.NewBuffer(jsonData),
	)
	if err != nil {
		return nil, fmt.Errorf("create http request failed: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.doRequestWithRetry(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("unexpected status code: %d, response: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response failed: %v", err)
	}

	var response SemanticDomainListResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %v", err)
	}

	return &response, nil
}

// ─── DD Group Relation (Semantic Domain ↔ Semantic Group) ────────────────────

type DDGroupRelation struct {
	ID                int    `json:"id"`
	SDID              string `json:"sd_id"`
	GroupID           string `json:"group_id"`
	AssociationReason string `json:"association_reason"`
}

type DDGroupRelationListResponse struct {
	Status string            `json:"status"`
	Data   []DDGroupRelation `json:"data"`
	Count  int               `json:"count"`
}

// GetRelationsBySDID returns all semantic group relations for a semantic domain.
// GET /dd_group_relations/sd/{sd_id}
func (c *APIClient) GetRelationsBySDID(ctx context.Context, sdID string) (*DDGroupRelationListResponse, error) {
	if sdID == "" {
		return nil, fmt.Errorf("sd_id is required")
	}

	httpReq, err := http.NewRequestWithContext(
		ctx,
		"GET",
		c.cfg.DataServicesBaseURL+"/dd_group_relations/sd/"+sdID,
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("create http request failed: %v", err)
	}

	resp, err := c.doRequestWithRetry(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("unexpected status code: %d, response: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response failed: %v", err)
	}

	var response DDGroupRelationListResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %v", err)
	}

	return &response, nil
}

// ─── Semantic Group ──────────────────────────────────────────────────────────

type SemanticGroupRecord struct {
	ID          string `json:"id"`
	GroupName   string `json:"group_name"`
	Description string `json:"description"`
	AgentCard   string `json:"agent_card"`
	Version     string `json:"version"`
	ParentID    string `json:"parent_id"`
}

type SemanticGroupResponse struct {
	Status  string              `json:"status"`
	Data    SemanticGroupRecord `json:"data"`
	Message string              `json:"message"`
}

// GetSemanticGroupByID fetches a semantic group by its ID.
// GET /semantic_groups/{group_id}
func (c *APIClient) GetSemanticGroupByID(ctx context.Context, groupID string) (*SemanticGroupResponse, error) {
	if groupID == "" {
		return nil, fmt.Errorf("group_id is required")
	}

	httpReq, err := http.NewRequestWithContext(
		ctx,
		"GET",
		c.cfg.DataServicesBaseURL+"/semantic_groups/"+groupID,
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("create http request failed: %v", err)
	}

	resp, err := c.doRequestWithRetry(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("unexpected status code: %d, response: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response failed: %v", err)
	}

	var response SemanticGroupResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %v", err)
	}

	return &response, nil
}

// ─── Fingerprint ─────────────────────────────────────────────────────────────

func (c *APIClient) FingerprintSearchByDD(ctx context.Context, req *FingerprintSearchByDDRequest) (*FingerprintListResponse, error) {
	if req.DdNamespace == "" || req.DdName == "" {
		return nil, fmt.Errorf("both dd_namespace and dd_name are required")
	}

	jsonData, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal search request failed: %v", err)
	}

	httpReq, err := http.NewRequestWithContext(
		ctx,
		"POST",
		c.cfg.DataServicesBaseURL+"/fingerprints/search/by-dd",
		bytes.NewBuffer(jsonData),
	)
	if err != nil {
		return nil, fmt.Errorf("create http request failed: %v", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.doRequestWithRetry(httpReq)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("unexpected status code: %d, response: %s", resp.StatusCode, string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response failed: %v", err)
	}

	var response FingerprintListResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("unmarshal response failed: %v", err)
	}

	return &response, nil
}

// func main() {
// 	cfg := LoadConfig()
// 	client := NewAPIClient(cfg)

// 	ctx, cancel := context.WithTimeout(context.Background(), cfg.HTTPTimeout)
// 	defer cancel()

// 	req := &FingerprintSearchByDDRequest{
// 		DdNamespace: "your_namespace",
// 		DdName:      "your_name",
// 	}

// 	response, err := client.FingerprintSearchByDD(ctx, req)
// 	if err != nil {
// 		fmt.Printf("Error searching fingerprints: %v\n", err)
// 		return
// 	}

// 	fmt.Printf("Search completed. Status: %s, Count: %d\n", response.Status, response.Count)
// 	for _, fp := range response.Data {
// 		fmt.Printf("Fingerprint ID: %s, Summary: %s\n", fp.FingerprintID, fp.FingerprintSummary)
// 	}
// }
