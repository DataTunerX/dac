package generator

import (
	"encoding/json"
	"testing"

	dacv1alpha1 "github.com/DataTunerX/dac/execution-engine/api/v1alpha1"
	corev1 "k8s.io/api/core/v1"
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
		CrossSGMaxHop:        "5",
		CrossSGMidExecRounds: "5",
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
	if m["CROSS_SG_MAX_HOP"] != "5" {
		t.Fatalf("CROSS_SG_MAX_HOP=%q, want %q", m["CROSS_SG_MAX_HOP"], "5")
	}
	if m["CROSS_SG_MID_EXEC_ROUNDS"] != "5" {
		t.Fatalf("CROSS_SG_MID_EXEC_ROUNDS=%q, want %q", m["CROSS_SG_MID_EXEC_ROUNDS"], "5")
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

func TestGenerateOrchestratorAgentEnvs_NormalWithSkillPolicy(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "sg-demo"
	dac.Namespace = "ns1"
	dac.Spec.DACType = "normal"
	dac.Spec.AgentCard.Name = "SGAgent"
	dac.Spec.AgentCard.Description = "desc"
	dac.Spec.DataPolicy.DataSourceType = "SemanticGroup"
	dac.Spec.DataPolicy.SemanticGroupID = "sg-123"
	dac.Spec.SkillPolicy = dacv1alpha1.SkillPolicy{
		Skills: []dacv1alpha1.SkillRef{
			{Namespace: "default", Name: "weather", Version: "1.0.0"},
			{Namespace: "team-a", Name: "web_fetch", Version: ""},
		},
	}
	envs := h.generateOrchestratorAgentEnvs(dac, "dac-sg-demo", "", nil)
	m := map[string]string{}
	for _, e := range envs {
		m[e.Name] = e.Value
	}
	if m["SKILLS"] == "" {
		t.Fatalf("expected SKILLS env for normal+skillPolicy, got %+v", m)
	}
	if m["SKILL_HUB_URL"] != "http://skill-hub.dac.svc.cluster.local:8000" {
		t.Fatalf("SKILL_HUB_URL=%q", m["SKILL_HUB_URL"])
	}
	if m["SKILLS_DOWNLOAD_DIR"] != "/app/skills/" {
		t.Fatalf("SKILLS_DOWNLOAD_DIR=%q", m["SKILLS_DOWNLOAD_DIR"])
	}
	if m["SKILL_DOWNLOAD_OVERWRITE"] != "true" {
		t.Fatalf("SKILL_DOWNLOAD_OVERWRITE=%q", m["SKILL_DOWNLOAD_OVERWRITE"])
	}
	var refs []skillRefForEnv
	if err := json.Unmarshal([]byte(m["SKILLS"]), &refs); err != nil {
		t.Fatalf("SKILLS not JSON: %v raw=%s", err, m["SKILLS"])
	}
	if len(refs) != 2 || refs[0].Name != "weather" || refs[1].Name != "web_fetch" {
		t.Fatalf("unexpected SKILLS refs: %+v", refs)
	}
}

func TestGenerateOrchestratorAgentEnvs_NormalWithoutSkillPolicy(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "sg-demo"
	dac.Namespace = "ns1"
	dac.Spec.DACType = "normal"
	dac.Spec.AgentCard.Name = "SGAgent"
	dac.Spec.DataPolicy.DataSourceType = "SemanticGroup"
	dac.Spec.DataPolicy.SemanticGroupID = "sg-123"
	envs := h.generateOrchestratorAgentEnvs(dac, "dac-sg-demo", "", nil)
	for _, e := range envs {
		if e.Name == "SKILLS" || e.Name == "SKILL_HUB_URL" {
			t.Fatalf("did not expect %s when skillPolicy empty, value=%q", e.Name, e.Value)
		}
	}
}

func TestGenerateNormalAgentEnvs_MemberCapabilityConfig(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Namespace = "ns1"
	dac.Spec.DACType = "normal"
	dac.Spec.AgentCard.Name = "SGAgent"
	dac.Spec.DataPolicy.DataSourceType = "SemanticGroup"
	dac.Spec.DataPolicy.SemanticGroupID = "sg-123"
	cfg := &DACConfig{
		SGMemberCapabilityEnabled:       "true",
		SGMemberCapabilityShadow:        "false",
		SGMemberCapabilityConcurrency:   "6",
		SGMemberCapabilityMemberTimeout: "7",
		SGMemberCapabilityTotalTimeout:  "19",
	}

	for name, envs := range map[string][]corev1.EnvVar{
		"orchestrator": h.generateOrchestratorAgentEnvs(dac, "dac-sg-demo", "", cfg),
		"expert":       h.generateExpertAgentEnvs(dac, "dac-sg-demo", "", cfg),
	} {
		values := map[string]string{}
		for _, env := range envs {
			values[env.Name] = env.Value
		}
		expected := map[string]string{
			"SG_MEMBER_CAPABILITY_CHECK_ENABLED":      "true",
			"SG_MEMBER_CAPABILITY_CHECK_SHADOW":       "false",
			"SG_MEMBER_CAPABILITY_MAX_CONCURRENCY":    "6",
			"SG_MEMBER_CAPABILITY_PER_MEMBER_TIMEOUT": "7",
			"SG_MEMBER_CAPABILITY_TOTAL_TIMEOUT":      "19",
		}
		for key, want := range expected {
			if got := values[key]; got != want {
				t.Fatalf("%s %s=%q, want %q", name, key, got, want)
			}
		}
		if name == "orchestrator" {
			if got := values["SG_MEMBER_CAPABILITY_CHECK_TIMEOUT"]; got != "19" {
				t.Fatalf("orchestrator SG_MEMBER_CAPABILITY_CHECK_TIMEOUT=%q, want %q", got, "19")
			}
		}
	}
}

func TestGenerateNormalAgentEnvs_MemberCapabilityConfigSkipsEmpty(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Namespace = "ns1"
	dac.Spec.DACType = "normal"
	dac.Spec.AgentCard.Name = "SGAgent"
	dac.Spec.DataPolicy.DataSourceType = "SemanticGroup"
	dac.Spec.DataPolicy.SemanticGroupID = "sg-123"
	// Simulates production dac-configuration without the new keys.
	cfg := &DACConfig{}

	keys := []string{
		"SG_MEMBER_CAPABILITY_CHECK_ENABLED",
		"SG_MEMBER_CAPABILITY_CHECK_SHADOW",
		"SG_MEMBER_CAPABILITY_MAX_CONCURRENCY",
		"SG_MEMBER_CAPABILITY_PER_MEMBER_TIMEOUT",
		"SG_MEMBER_CAPABILITY_TOTAL_TIMEOUT",
		"SG_MEMBER_CAPABILITY_CHECK_TIMEOUT",
	}
	for name, envs := range map[string][]corev1.EnvVar{
		"orchestrator": h.generateOrchestratorAgentEnvs(dac, "dac-sg-demo", "", cfg),
		"expert":       h.generateExpertAgentEnvs(dac, "dac-sg-demo", "", cfg),
	} {
		present := map[string]bool{}
		for _, env := range envs {
			present[env.Name] = true
		}
		for _, key := range keys {
			if present[key] {
				t.Fatalf("%s unexpectedly injected empty %s", name, key)
			}
		}
	}
}

func TestPodTemplateObjectMeta_SkillPolicyAnnotation(t *testing.T) {
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Spec.SkillPolicy = dacv1alpha1.SkillPolicy{
		Skills: []dacv1alpha1.SkillRef{
			{Namespace: "default", Name: "weather"},
		},
	}
	om := podTemplateObjectMeta(map[string]string{"app": "x"}, dac)
	if om.Annotations["dac.dac.io/skill-policy-sha256"] == "" {
		t.Fatalf("expected skill-policy-sha256 annotation, got %+v", om.Annotations)
	}
}
