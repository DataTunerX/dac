package generator

import (
	"encoding/json"
	"testing"

	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
)

func TestBuildSkillsEnvJSON(t *testing.T) {
	dac := &dacv1alpha1.DataAgentContainer{
		Spec: dacv1alpha1.DataAgentContainerSpec{
			SkillPolicy: dacv1alpha1.SkillPolicy{
				Skills: []dacv1alpha1.SkillRef{
					{Namespace: "default", Name: "weather", Version: "1.2.0"},
					{Namespace: "team-a", Name: "report", Version: ""},
				},
			},
		},
	}
	got, err := buildSkillsEnvJSON(dac)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	var refs []skillRefForEnv
	if err := json.Unmarshal([]byte(got), &refs); err != nil {
		t.Fatalf("invalid json: %v raw=%s", err, got)
	}
	if len(refs) != 2 {
		t.Fatalf("want 2 refs, got %d (%s)", len(refs), got)
	}
	if refs[0].Namespace != "default" || refs[0].Name != "weather" || refs[0].Version != "1.2.0" {
		t.Fatalf("unexpected first ref: %+v", refs[0])
	}
	if refs[1].Namespace != "team-a" || refs[1].Name != "report" || refs[1].Version != "" {
		t.Fatalf("unexpected second ref: %+v", refs[1])
	}
}

func TestGenerateSkillDataAgentContainerService_SinglePort(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "demo"
	dac.Namespace = "default"
	svc := h.GenerateSkillDataAgentContainerService(dac, map[string]string{"app": "demo"}, nil)
	if svc.Name != "dac-demo" {
		t.Fatalf("service name: got %s", svc.Name)
	}
	if len(svc.Spec.Ports) != 1 || svc.Spec.Ports[0].Port != 10100 {
		t.Fatalf("want single port 10100, got %+v", svc.Spec.Ports)
	}
}

func TestGenerateSkillAgentEnvs_RegisterAndSkills(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "demo"
	dac.Namespace = "ns1"
	dac.Spec.AgentCard.Name = "MySkill"
	dac.Spec.AgentCard.Description = "desc"
	dac.Spec.ExpertAgentMaxSteps = "15"
	envs := h.generateSkillAgentEnvs(dac, "dac-demo", `[{"namespace":"default","name":"weather","version":""}]`, &DACConfig{
		ObservationBaseURL:   "http://lf",
		ObservationSecretKey: "sk",
		ObservationPublicKey: "pk",
	})
	m := map[string]string{}
	for _, e := range envs {
		m[e.Name] = e.Value
	}
	if m["REGISTER_AGENT"] != "true" {
		t.Fatalf("REGISTER_AGENT=%q", m["REGISTER_AGENT"])
	}
	if m["Agent_Host"] != "dac-demo.ns1.svc.cluster.local" {
		t.Fatalf("Agent_Host=%q", m["Agent_Host"])
	}
	if m["Agent_Port"] != "10100" {
		t.Fatalf("Agent_Port=%q", m["Agent_Port"])
	}
	if m["SKILLS"] == "" || m["SKILL_HUB_URL"] == "" {
		t.Fatalf("missing SKILLS/SKILL_HUB_URL: %+v", m)
	}
	if m["LOCAL_SKILL_MAX_STEPS"] != "15" {
		t.Fatalf("LOCAL_SKILL_MAX_STEPS=%q", m["LOCAL_SKILL_MAX_STEPS"])
	}
	args := h.generateSkillAgentArgs(dac, &LLMConfig{Provider: "openai_compatible", APIKey: "k", BaseURL: "u", Model: "m"}, nil)
	foundDB := false
	for i := 0; i+1 < len(args); i++ {
		if args[i] == "--redis-db" && args[i+1] == "2" {
			foundDB = true
		}
		if args[i] == "--port" && args[i+1] != "10100" {
			t.Fatalf("port=%s", args[i+1])
		}
	}
	if !foundDB {
		t.Fatalf("expected --redis-db 2 in %v", args)
	}
}
