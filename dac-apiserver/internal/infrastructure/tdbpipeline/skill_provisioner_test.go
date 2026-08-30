package tdbpipeline

import (
	"archive/zip"
	"bytes"
	"io"
	"strings"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

func TestSkillNameForTargetPrefersConfiguredName(t *testing.T) {
	target := domain.TDBPipelineTarget{ID: "archeology", Domain: "archeology", SkillAgent: "tdb-archeology-qa"}
	if got := SkillNameForTarget(target); got != "tdb-archeology-qa" {
		t.Fatalf("expected the configured skill name, got %q", got)
	}
}

func TestSkillNameForTargetDerivesFromTargetID(t *testing.T) {
	// The paper test target shares its domain with the live archeology target,
	// so the name must come from the target ID, not the domain.
	target := domain.TDBPipelineTarget{ID: "archeology_papers_test", Domain: "archeology"}
	if got := SkillNameForTarget(target); got != "tdb-archeology-papers-test-qa" {
		t.Fatalf("unexpected derived name %q", got)
	}
}

func TestSkillNameForTargetFallsBackToDomain(t *testing.T) {
	target := domain.TDBPipelineTarget{ID: "考古", Domain: "geo_environment"}
	if got := SkillNameForTarget(target); got != "tdb-geo-environment-qa" {
		t.Fatalf("unexpected fallback name %q", got)
	}
}

func TestBuildSkillArchiveLayoutAndSubstitution(t *testing.T) {
	target := domain.TDBPipelineTarget{
		ID:         "archeology_papers_test",
		Domain:     "archeology",
		Label:      "考古学（论文测试库）",
		GatewayURL: "http://10.124.48.91:8996",
	}
	name := "tdb-archeology-papers-test-qa"

	raw, err := buildSkillArchive(name, target, "academic_papers")
	if err != nil {
		t.Fatalf("buildSkillArchive: %v", err)
	}

	zr, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		t.Fatalf("open archive: %v", err)
	}

	contents := map[string]string{}
	for _, f := range zr.File {
		rc, err := f.Open()
		if err != nil {
			t.Fatalf("open %s: %v", f.Name, err)
		}
		body, err := io.ReadAll(rc)
		rc.Close()
		if err != nil {
			t.Fatalf("read %s: %v", f.Name, err)
		}
		contents[f.Name] = string(body)
	}

	// skill-hub requires _meta.json; it does not generate one.
	for _, want := range []string{
		name + "/SKILL.md",
		name + "/_meta.json",
		name + "/references/gateway_api_doc.md",
	} {
		if _, ok := contents[want]; !ok {
			t.Fatalf("archive is missing %s (has %v)", want, keys(contents))
		}
	}

	skill := contents[name+"/SKILL.md"]
	if !strings.Contains(skill, "name: "+name) {
		t.Error("SKILL.md front matter does not carry the generated name")
	}
	if !strings.Contains(skill, "http://10.124.48.91:8996") {
		t.Error("SKILL.md does not point at the target gateway")
	}
	if !strings.Contains(skill, `domain: "archeology"`) {
		t.Error("SKILL.md does not carry the target domain")
	}
	if strings.Contains(skill, "{{") {
		t.Error("SKILL.md still contains unrendered template placeholders")
	}

	if !strings.Contains(contents[name+"/_meta.json"], `"slug": "`+name+`"`) {
		t.Error("_meta.json slug does not match the skill name")
	}
}

func keys(m map[string]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
