package skillhub

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"mime/multipart"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/bytedance/sonic"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

type Client struct {
	baseURL string
	http    *http.Client
	logger  *slog.Logger
}

func NewClient(baseURL string, timeout time.Duration, logger *slog.Logger) *Client {
	if logger == nil {
		logger = slog.Default()
	}
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	return &Client{
		baseURL: strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		http:    &http.Client{Timeout: timeout},
		logger:  logger,
	}
}

type skillHubError struct {
	Error      string `json:"error"`
	StatusCode int    `json:"status_code"`
}

type skillInfoRaw struct {
	Name              string   `json:"name"`
	Namespace         string   `json:"namespace"`
	Description       string   `json:"description"`
	Version           string   `json:"version"`
	Filename          string   `json:"filename"`
	AvailableVersions []string `json:"available_versions"`
}

type skillListRaw struct {
	Count  int            `json:"count"`
	Skills []skillInfoRaw `json:"skills"`
}

type namespaceInfoRaw struct {
	ID         string `json:"id"`
	Visibility string `json:"visibility"`
}

type namespaceListRaw struct {
	Count      int                `json:"count"`
	Namespaces []namespaceInfoRaw `json:"namespaces"`
}

type namespaceExistsRaw struct {
	Namespace string `json:"namespace"`
	Exists    bool   `json:"exists"`
}

func (c *Client) ListNamespaces(ctx context.Context) ([]domain.SkillNamespace, error) {
	var raw namespaceListRaw
	if err := c.doJSON(ctx, http.MethodGet, "/namespaces", nil, "", &raw); err != nil {
		return nil, err
	}
	out := make([]domain.SkillNamespace, 0, len(raw.Namespaces))
	for _, ns := range raw.Namespaces {
		out = append(out, domain.SkillNamespace{ID: ns.ID, Visibility: ns.Visibility})
	}
	return out, nil
}

func (c *Client) NamespaceExists(ctx context.Context, namespace string) (bool, error) {
	if err := validateNamespace(namespace); err != nil {
		return false, err
	}
	var raw namespaceExistsRaw
	path := "/namespaces/" + url.PathEscape(namespace) + "/exists"
	if err := c.doJSON(ctx, http.MethodGet, path, nil, "", &raw); err != nil {
		return false, err
	}
	return raw.Exists, nil
}

func (c *Client) CreateNamespace(ctx context.Context, namespace string) (*domain.SkillNamespace, error) {
	if err := validateNamespace(namespace); err != nil {
		return nil, err
	}
	var raw namespaceInfoRaw
	path := "/namespaces/" + url.PathEscape(namespace)
	if err := c.doJSON(ctx, http.MethodPost, path, nil, "", &raw); err != nil {
		return nil, err
	}
	return &domain.SkillNamespace{ID: raw.ID, Visibility: raw.Visibility}, nil
}

func (c *Client) DeleteNamespace(ctx context.Context, namespace string) error {
	if err := validateNamespace(namespace); err != nil {
		return err
	}
	path := "/namespaces/" + url.PathEscape(namespace)
	return c.doJSON(ctx, http.MethodDelete, path, nil, "", nil)
}

func (c *Client) ListSkills(ctx context.Context, namespace string) ([]domain.SkillInfo, error) {
	if err := validateNamespace(namespace); err != nil {
		return nil, err
	}
	var raw skillListRaw
	path := "/namespaces/" + url.PathEscape(namespace) + "/skills"
	if err := c.doJSON(ctx, http.MethodGet, path, nil, "", &raw); err != nil {
		return nil, err
	}
	return mapSkills(raw.Skills), nil
}

type skillScriptRaw struct {
	ScriptName  string `json:"script_name"`
	Interpreter string `json:"interpreter"`
}

type skillDetailRaw struct {
	Name              string           `json:"name"`
	Namespace         string           `json:"namespace"`
	Description       string           `json:"description"`
	Detail            string           `json:"detail"`
	Version           string           `json:"version"`
	Filename          string           `json:"filename"`
	AvailableVersions []string         `json:"available_versions"`
	AllowedTools      []string         `json:"allowed_tools"`
	Scripts           []skillScriptRaw `json:"scripts"`
	ResourceDirs      []string         `json:"resource_dirs"`
}

// GetSkill loads zip-backed skill metadata from skill-hub
// (GET /namespaces/{ns}/skills/{name}/detail).
func (c *Client) GetSkill(ctx context.Context, namespace, name, version string) (*domain.SkillDetail, error) {
	if err := validateNamespace(namespace); err != nil {
		return nil, err
	}
	if err := validateName(name); err != nil {
		return nil, err
	}
	// skill-hub uses /detail so the path does not collide with /{name}.zip downloads.
	path := "/namespaces/" + url.PathEscape(namespace) + "/skills/" + url.PathEscape(name) + "/detail"
	if version != "" {
		path += "?version=" + url.QueryEscape(version)
	}
	var raw skillDetailRaw
	if err := c.doJSON(ctx, http.MethodGet, path, nil, "", &raw); err != nil {
		return nil, err
	}
	versions := raw.AvailableVersions
	if versions == nil {
		versions = []string{}
	}
	tools := raw.AllowedTools
	if tools == nil {
		tools = []string{}
	}
	dirs := raw.ResourceDirs
	if dirs == nil {
		dirs = []string{}
	}
	scripts := make([]domain.SkillScriptInfo, 0, len(raw.Scripts))
	for _, s := range raw.Scripts {
		scripts = append(scripts, domain.SkillScriptInfo{
			ScriptName:  s.ScriptName,
			Interpreter: s.Interpreter,
		})
	}
	return &domain.SkillDetail{
		Name:              raw.Name,
		Namespace:         raw.Namespace,
		Description:       raw.Description,
		Detail:            raw.Detail,
		Version:           raw.Version,
		Filename:          raw.Filename,
		AvailableVersions: versions,
		AllowedTools:      tools,
		Scripts:           scripts,
		ResourceDirs:      dirs,
	}, nil
}

type createSkillBody struct {
	Name         string   `json:"name"`
	Description  string   `json:"description"`
	Detail       string   `json:"detail"`
	Version      string   `json:"version"`
	AllowedTools []string `json:"allowed_tools"`
}

func (c *Client) CreateSkill(ctx context.Context, namespace string, req domain.CreateSkillRequest) (*domain.SkillInfo, error) {
	if err := validateNamespace(namespace); err != nil {
		return nil, err
	}
	if strings.TrimSpace(req.Name) == "" {
		return nil, domain.NewInvalidInputError("name is required")
	}
	if strings.TrimSpace(req.Description) == "" {
		return nil, domain.NewInvalidInputError("description is required")
	}
	tools := req.AllowedTools
	if tools == nil {
		tools = []string{}
	}
	payload := createSkillBody{
		Name:         strings.TrimSpace(req.Name),
		Description:  strings.TrimSpace(req.Description),
		Detail:       req.Detail,
		Version:      strings.TrimSpace(req.Version),
		AllowedTools: tools,
	}
	if payload.Version == "" {
		payload.Version = "1.0.0"
	}
	body, err := sonic.Marshal(payload)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	var raw skillInfoRaw
	path := "/namespaces/" + url.PathEscape(namespace) + "/skills/create"
	if err := c.doJSON(ctx, http.MethodPost, path, body, "application/json", &raw); err != nil {
		return nil, err
	}
	info := mapSkill(raw)
	return &info, nil
}

func (c *Client) UploadSkill(ctx context.Context, namespace, filename string, r io.Reader) (*domain.SkillInfo, error) {
	if err := validateNamespace(namespace); err != nil {
		return nil, err
	}
	if strings.TrimSpace(filename) == "" {
		return nil, domain.NewInvalidInputError("filename is required")
	}
	if r == nil {
		return nil, domain.NewInvalidInputError("file is required")
	}
	if c.baseURL == "" {
		return nil, domain.NewInternalError(fmt.Errorf("skill-hub base URL is empty"))
	}

	pr, pw := io.Pipe()
	mw := multipart.NewWriter(pw)
	go func() {
		defer pw.Close()
		part, err := mw.CreateFormFile("file", filename)
		if err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		if _, err := io.Copy(part, r); err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		if err := mw.Close(); err != nil {
			_ = pw.CloseWithError(err)
			return
		}
	}()

	path := "/namespaces/" + url.PathEscape(namespace) + "/skills"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, pr)
	if err != nil {
		_ = pr.Close()
		return nil, domain.NewInternalError(err)
	}
	req.Header.Set("Content-Type", mw.FormDataContentType())

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	if err := mapHTTPError(resp.StatusCode, body); err != nil {
		return nil, err
	}

	var raw skillInfoRaw
	if err := sonic.Unmarshal(body, &raw); err != nil {
		return nil, domain.NewInternalError(err)
	}
	info := mapSkill(raw)
	return &info, nil
}

func (c *Client) DownloadSkill(ctx context.Context, namespace, name, version string) (*domain.SkillDownload, error) {
	if err := validateNamespace(namespace); err != nil {
		return nil, err
	}
	if err := validateName(name); err != nil {
		return nil, err
	}
	if c.baseURL == "" {
		return nil, domain.NewInternalError(fmt.Errorf("skill-hub base URL is empty"))
	}

	path := "/namespaces/" + url.PathEscape(namespace) + "/skills/" + url.PathEscape(name) + ".zip"
	u := c.baseURL + path
	if version != "" {
		u += "?version=" + url.QueryEscape(version)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, domain.NewInternalError(err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		defer resp.Body.Close()
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, mapHTTPError(resp.StatusCode, body)
	}

	filename := name + ".zip"
	if cd := resp.Header.Get("Content-Disposition"); strings.Contains(cd, "filename=") {
		if parts := strings.Split(cd, "filename="); len(parts) > 1 {
			filename = strings.Trim(parts[1], `"' `)
		}
	}

	return &domain.SkillDownload{
		Filename: filename,
		Version:  resp.Header.Get("X-Skill-Version"),
		Body:     resp.Body,
		Size:     resp.ContentLength,
	}, nil
}

func (c *Client) DeleteSkill(ctx context.Context, namespace, name, version string) error {
	if err := validateNamespace(namespace); err != nil {
		return err
	}
	if err := validateName(name); err != nil {
		return err
	}
	path := "/namespaces/" + url.PathEscape(namespace) + "/skills/" + url.PathEscape(name) + ".zip"
	if version != "" {
		path += "?version=" + url.QueryEscape(version)
	}
	return c.doJSON(ctx, http.MethodDelete, path, nil, "", nil)
}

func (c *Client) Reload(ctx context.Context) ([]domain.SkillInfo, error) {
	var raw skillListRaw
	if err := c.doJSON(ctx, http.MethodPost, "/skills/reload", nil, "", &raw); err != nil {
		return nil, err
	}
	return mapSkills(raw.Skills), nil
}

func (c *Client) doJSON(ctx context.Context, method, path string, body []byte, contentType string, out any) error {
	if c.baseURL == "" {
		return domain.NewInternalError(fmt.Errorf("skill-hub base URL is empty"))
	}

	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return domain.NewInternalError(err)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return domain.NewInternalError(err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return domain.NewInternalError(err)
	}
	// 204 No Content
	if resp.StatusCode == http.StatusNoContent {
		return nil
	}
	if err := mapHTTPError(resp.StatusCode, raw); err != nil {
		return err
	}
	if out == nil || len(raw) == 0 {
		return nil
	}
	if err := sonic.Unmarshal(raw, out); err != nil {
		return domain.NewInternalError(err)
	}
	return nil
}

func mapHTTPError(status int, body []byte) error {
	if status >= 200 && status < 300 {
		return nil
	}

	msg := strings.TrimSpace(string(body))
	var hubErr skillHubError
	if err := sonic.Unmarshal(body, &hubErr); err == nil && hubErr.Error != "" {
		msg = hubErr.Error
	}
	if msg == "" {
		msg = fmt.Sprintf("skill-hub HTTP %d", status)
	}

	switch status {
	case http.StatusBadRequest:
		return domain.NewInvalidInputError(msg)
	case http.StatusNotFound:
		return domain.NewNotFoundError("skill", msg)
	case http.StatusConflict:
		// skill-hub uses 409 for both already-exists and non-empty namespace.
		lower := strings.ToLower(msg)
		if strings.Contains(lower, "already exists") {
			return domain.NewAlreadyExistsError("skill namespace", msg)
		}
		return domain.NewConflictError(msg)
	default:
		return domain.NewInternalError(fmt.Errorf("skill-hub HTTP %d: %s", status, msg))
	}
}

func mapSkills(items []skillInfoRaw) []domain.SkillInfo {
	out := make([]domain.SkillInfo, 0, len(items))
	for _, item := range items {
		out = append(out, mapSkill(item))
	}
	return out
}

func mapSkill(item skillInfoRaw) domain.SkillInfo {
	versions := item.AvailableVersions
	if versions == nil {
		versions = []string{}
	}
	return domain.SkillInfo{
		Name:              item.Name,
		Namespace:         item.Namespace,
		Description:       item.Description,
		Version:           item.Version,
		Filename:          item.Filename,
		AvailableVersions: versions,
	}
}

func validateNamespace(namespace string) error {
	ns := strings.TrimSpace(namespace)
	if ns == "" {
		return domain.NewInvalidInputError("namespace is required")
	}
	return nil
}

func validateName(name string) error {
	if strings.TrimSpace(name) == "" {
		return domain.NewInvalidInputError("skill name is required")
	}
	return nil
}
