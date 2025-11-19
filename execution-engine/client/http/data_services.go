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
