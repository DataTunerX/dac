package tdbpipeline

import (
	"archive/zip"
	"bytes"
	"context"
	_ "embed"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"text/template"
	"unicode"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

//go:embed assets/skill_template.md
var skillTemplateSource string

//go:embed assets/gateway_api_doc.md
var gatewayAPIDoc string

// skillVersion is the version every generated skill is published under.
// skill-hub keys a skill by (namespace, name, version) and overwrites on an
// exact match, so republishing the same target refreshes it in place instead
// of accumulating versions.
const skillVersion = "1.0.0"

var skillTemplate = template.Must(template.New("skill").Parse(skillTemplateSource))

// skillTemplateData is what the SKILL.md template is rendered with.
type skillTemplateData struct {
	SkillName   string
	Title       string
	Subject     string
	Domain      string
	TargetID    string
	GatewayURL  string
	GatewayHost string
	Collection  string
}

// SkillPublisher is the skill-hub upload surface the provisioner needs.
// *skillhub.Client satisfies it.
type SkillPublisher interface {
	ListSkills(ctx context.Context, namespace string) ([]domain.SkillInfo, error)
	UploadSkill(ctx context.Context, namespace, filename string, r io.Reader) (*domain.SkillInfo, error)
}

// SkillProvisioner publishes a TDB QA skill for a pipeline target, so a corpus
// that was just ingested becomes answerable without anyone hand-writing a skill.
//
// The skill is bound to the target's gateway, which is what makes one skill per
// target the right granularity: a gateway is a database, and a skill that spans
// two of them would silently answer across corpora.
type SkillProvisioner struct {
	publisher SkillPublisher
	namespace string
	enabled   bool
	logger    *slog.Logger
}

func NewSkillProvisioner(publisher SkillPublisher, namespace string, enabled bool, logger *slog.Logger) *SkillProvisioner {
	if logger == nil {
		logger = slog.Default()
	}
	if strings.TrimSpace(namespace) == "" {
		namespace = "default"
	}
	return &SkillProvisioner{
		publisher: publisher,
		namespace: namespace,
		enabled:   enabled,
		logger:    logger,
	}
}

// EnsureSkill publishes the skill for a target if it is not already in the hub.
//
// It is safe to call repeatedly and from concurrent run refreshes: an existing
// skill with the same name short-circuits before any upload. Failure is
// reported but never fails the run -- ingestion already succeeded, and a
// missing skill is recoverable by re-running this.
func (p *SkillProvisioner) EnsureSkill(ctx context.Context, target domain.TDBPipelineTarget, collection string) (string, error) {
	if !p.enabled {
		return "", nil
	}
	if p.publisher == nil {
		return "", fmt.Errorf("skill provisioning enabled without a skill-hub client")
	}

	name := SkillNameForTarget(target)
	if name == "" {
		return "", fmt.Errorf("cannot derive a skill name for target %q", target.ID)
	}

	existing, err := p.publisher.ListSkills(ctx, p.namespace)
	if err != nil {
		return "", fmt.Errorf("list skills: %w", err)
	}
	for _, skill := range existing {
		if skill.Name == name {
			// Already published. The skill queries the gateway live, so an
			// existing skill already covers everything just ingested.
			return name, nil
		}
	}

	archive, err := buildSkillArchive(name, target, collection)
	if err != nil {
		return "", err
	}

	filename := fmt.Sprintf("%s-%s.zip", name, skillVersion)
	if _, err := p.publisher.UploadSkill(ctx, p.namespace, filename, bytes.NewReader(archive)); err != nil {
		return "", fmt.Errorf("upload skill %s: %w", name, err)
	}

	p.logger.Info("published TDB skill for pipeline target",
		"skill", name, "namespace", p.namespace,
		"target", target.ID, "gateway", target.GatewayURL)
	return name, nil
}

// SkillNameForTarget is the skill name a target maps to. A target that already
// names a skill in configuration wins, so hand-published skills such as
// tdb-archeology-qa keep their name; otherwise the name is derived from the
// pipeline target ID.
func SkillNameForTarget(target domain.TDBPipelineTarget) string {
	if configured := strings.TrimSpace(target.SkillAgent); configured != "" {
		return configured
	}
	slug := slugify(target.ID)
	if slug == "" {
		slug = slugify(target.Domain)
	}
	if slug == "" {
		return ""
	}
	return "tdb-" + slug + "-qa"
}

// buildSkillArchive renders the skill and packs it in the layout skill-hub
// expects: <name>/SKILL.md, <name>/_meta.json and the gateway reference.
// _meta.json is required by the upload endpoint; skill-hub does not generate it.
func buildSkillArchive(name string, target domain.TDBPipelineTarget, collection string) ([]byte, error) {
	subject := target.Label
	if strings.TrimSpace(subject) == "" {
		subject = strings.ReplaceAll(target.Domain, "_", " ")
	}

	data := skillTemplateData{
		SkillName:   name,
		Title:       "TDB " + subject + " QA",
		Subject:     subject,
		Domain:      target.Domain,
		TargetID:    target.ID,
		GatewayURL:  target.GatewayURL,
		GatewayHost: strings.TrimPrefix(strings.TrimPrefix(target.GatewayURL, "http://"), "https://"),
		Collection:  collection,
	}

	var skillMD bytes.Buffer
	if err := skillTemplate.Execute(&skillMD, data); err != nil {
		return nil, fmt.Errorf("render skill template: %w", err)
	}

	meta := fmt.Sprintf("{\n  \"version\": %q,\n  \"slug\": %q\n}\n", skillVersion, name)

	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	files := []struct {
		path    string
		content string
	}{
		{name + "/SKILL.md", skillMD.String()},
		{name + "/_meta.json", meta},
		{name + "/references/gateway_api_doc.md", gatewayAPIDoc},
	}
	for _, f := range files {
		w, err := zw.Create(f.path)
		if err != nil {
			return nil, fmt.Errorf("create %s in archive: %w", f.path, err)
		}
		if _, err := w.Write([]byte(f.content)); err != nil {
			return nil, fmt.Errorf("write %s in archive: %w", f.path, err)
		}
	}
	if err := zw.Close(); err != nil {
		return nil, fmt.Errorf("finalize archive: %w", err)
	}
	return buf.Bytes(), nil
}

// slugify reduces an identifier to lowercase ASCII words joined by "-".
func slugify(raw string) string {
	var b strings.Builder
	lastDash := true
	for _, r := range strings.ToLower(strings.TrimSpace(raw)) {
		switch {
		case unicode.IsLetter(r) && r < unicode.MaxASCII, unicode.IsDigit(r) && r < unicode.MaxASCII:
			b.WriteRune(r)
			lastDash = false
		default:
			if !lastDash {
				b.WriteRune('-')
				lastDash = true
			}
		}
	}
	return strings.Trim(b.String(), "-")
}
