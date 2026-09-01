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
		TDBBaseURL:           "http://tdb.dac.svc.cluster.local:8080",
	}, nil)
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
	if m["TDB_BASE_URL"] != "http://tdb.dac.svc.cluster.local:8080" {
		t.Fatalf("TDB_BASE_URL=%q", m["TDB_BASE_URL"])
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

func TestAppendTDBBaseURLEnvSkipsEmptyURL(t *testing.T) {
	envs := appendTDBBaseURLEnv(nil, &DACConfig{})
	if len(envs) != 0 {
		t.Fatalf("unexpected envs: %+v", envs)
	}
}

func TestConfigureLocalSkillAttachments(t *testing.T) {
	dac := &dacv1alpha1.DataAgentContainer{
		Spec: dacv1alpha1.DataAgentContainerSpec{
			DACType: "normal",
			SkillPolicy: dacv1alpha1.SkillPolicy{Skills: []dacv1alpha1.SkillRef{
				{Namespace: "team-a", Name: "report", Version: "1.0.0"},
			}},
		},
	}
	pod := corev1.PodSpec{Containers: []corev1.Container{
		{Name: "orchestrator"},
		{Name: "expert"},
	}}

	if err := configureLocalSkillAttachments(dac, &pod); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pod.Volumes) != 1 || pod.Volumes[0].Name != localSkillsVolumeName || pod.Volumes[0].EmptyDir == nil {
		t.Fatalf("unexpected volumes: %+v", pod.Volumes)
	}
	if len(pod.Containers[1].Env) != 0 || len(pod.Containers[1].VolumeMounts) != 0 {
		t.Fatalf("expert container must not receive local skills: %+v", pod.Containers[1])
	}

	env := map[string]string{}
	for _, item := range pod.Containers[0].Env {
		env[item.Name] = item.Value
	}
	if env["ENABLE_LOCAL_SKILLS"] != "true" || env["LOCAL_SKILLS_DIR"] != localSkillsMountPath {
		t.Fatalf("missing local skill env: %+v", env)
	}
	if env["SKILL_SYNC_WATCH_ALL"] != "false" {
		t.Fatalf("local attachments must not watch all skills: %+v", env)
	}
	if env["LOCAL_SKILL_FORCE_ATTACHED"] != "true" {
		t.Fatalf("local attachments must force in-DAC execution: %+v", env)
	}
	var refs []skillRefForEnv
	if err := json.Unmarshal([]byte(env["SKILLS"]), &refs); err != nil || len(refs) != 1 {
		t.Fatalf("invalid SKILLS env: %q err=%v", env["SKILLS"], err)
	}
	if refs[0].Namespace != "team-a" || refs[0].Version != "1.0.0" {
		t.Fatalf("unexpected ref: %+v", refs[0])
	}
}

func TestConfigureLocalSkillAttachmentsSkippedForDedicatedSkillDAC(t *testing.T) {
	dac := &dacv1alpha1.DataAgentContainer{
		Spec: dacv1alpha1.DataAgentContainerSpec{
			DACType: "skill",
			SkillPolicy: dacv1alpha1.SkillPolicy{Skills: []dacv1alpha1.SkillRef{
				{Namespace: "default", Name: "weather"},
			}},
		},
	}
	pod := corev1.PodSpec{Containers: []corev1.Container{{Name: "skill-agent"}}}
	if err := configureLocalSkillAttachments(dac, &pod); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(pod.Volumes) != 0 || len(pod.Containers[0].Env) != 0 {
		t.Fatalf("dedicated skill DAC should be unchanged: %+v", pod)
	}
}

func TestConfigureMultipleLocalSkillAttachmentsForceInDAC(t *testing.T) {
	dac := &dacv1alpha1.DataAgentContainer{
		Spec: dacv1alpha1.DataAgentContainerSpec{
			DACType: "normal",
			SkillPolicy: dacv1alpha1.SkillPolicy{Skills: []dacv1alpha1.SkillRef{
				{Namespace: "default", Name: "weather"},
				{Namespace: "team-a", Name: "report"},
			}},
		},
	}
	pod := corev1.PodSpec{Containers: []corev1.Container{{Name: "orchestrator"}}}
	if err := configureLocalSkillAttachments(dac, &pod); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	env := map[string]string{}
	for _, item := range pod.Containers[0].Env {
		env[item.Name] = item.Value
	}
	if env["LOCAL_SKILL_FORCE_ATTACHED"] != "true" {
		t.Fatalf("multiple local attachments must remain inside DAC: %+v", env)
	}
}

func TestResolveDACImagePullPolicy(t *testing.T) {
	if got := resolveDACImagePullPolicy(&DACConfig{ImagePullPolicy: corev1.PullAlways}); got != corev1.PullAlways {
		t.Fatalf("configured policy=%q", got)
	}
	if got := resolveDACImagePullPolicy(&DACConfig{ImagePullPolicy: "invalid"}); got != corev1.PullIfNotPresent {
		t.Fatalf("invalid policy fallback=%q", got)
	}
	if got := resolveDACImagePullPolicy(nil); got != corev1.PullIfNotPresent {
		t.Fatalf("nil policy fallback=%q", got)
	}
}

// enable_thinking is a DashScope/Qwen extension that the real OpenAI API rejects
// with 400. The operator must switch it off for those endpoints, otherwise every
// LLM call from the generated agent fails.
func TestGenerateSkillAgentEnvsDisablesEnableThinkingForOpenAI(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "demo"
	dac.Namespace = "ns1"

	cases := []struct {
		name    string
		baseURL string
		want    bool
	}{
		{name: "openai", baseURL: "https://api.openai.com/v1", want: true},
		{name: "openai uppercase", baseURL: "https://API.OpenAI.com/v1", want: true},
		{name: "self-hosted vllm", baseURL: "http://10.124.48.200:8001/v1", want: false},
		{name: "dashscope", baseURL: "https://dashscope.aliyuncs.com/compatible-mode/v1", want: false},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			envs := h.generateSkillAgentEnvs(dac, "dac-demo", "[]", &DACConfig{}, &LLMConfig{BaseURL: tc.baseURL})

			got := ""
			found := false
			for _, e := range envs {
				if e.Name == "ENABLE_THINKING_PARAM" {
					got, found = e.Value, true
				}
			}
			if found != tc.want {
				t.Fatalf("ENABLE_THINKING_PARAM present=%v, want %v (base-url %s)", found, tc.want, tc.baseURL)
			}
			if tc.want && got != "false" {
				t.Fatalf("ENABLE_THINKING_PARAM=%q, want \"false\"", got)
			}
		})
	}
}

// A nil LLMConfig must not panic or emit the override.
func TestAppendEnableThinkingEnvNilConfig(t *testing.T) {
	if envs := appendEnableThinkingEnv(nil, nil); len(envs) != 0 {
		t.Fatalf("expected no envs for nil llmConfig, got %v", envs)
	}
}

// A skill agent bound to an explicit skillPolicy must not also subscribe to the
// whole Skill Hub namespace: watch-all made every agent load every tdb-* skill
// and then claim those domains in its capability check.
func TestGenerateSkillAgentEnvs_ExplicitPolicyDisablesWatchAll(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "geo"
	dac.Namespace = "default"
	dac.Spec.SkillPolicy.Skills = []dacv1alpha1.SkillRef{
		{Namespace: "default", Name: "tdb-geo-environment-qa", Version: "1.0.0"},
	}

	m := map[string]string{}
	for _, e := range h.generateSkillAgentEnvs(dac, "dac-geo", `[]`, nil, nil) {
		m[e.Name] = e.Value
	}
	if m["SKILL_SYNC_WATCH_ALL"] != "false" {
		t.Fatalf("expected watch-all disabled for an explicit policy, got %q", m["SKILL_SYNC_WATCH_ALL"])
	}
}

// With no policy the agent has no skills of its own, so leave the default alone
// rather than pinning it to a value that would give the agent nothing at all.
func TestGenerateSkillAgentEnvs_EmptyPolicyLeavesWatchAllUnset(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "bare"
	dac.Namespace = "default"

	for _, e := range h.generateSkillAgentEnvs(dac, "dac-bare", `[]`, nil, nil) {
		if e.Name == "SKILL_SYNC_WATCH_ALL" {
			t.Fatalf("expected SKILL_SYNC_WATCH_ALL to stay unset, got %q", e.Value)
		}
	}
}

// The skill-agent subprocess timeout defaults to 30s, which is too short for
// skills that shell out. The operator passes the deployment's configured value.
func TestGenerateSkillAgentEnvs_SkillCmdTimeout(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "build"
	dac.Namespace = "default"

	m := map[string]string{}
	for _, e := range h.generateSkillAgentEnvs(dac, "dac-build", `[]`, &DACConfig{SkillCmdTimeoutSeconds: "300"}, nil) {
		m[e.Name] = e.Value
	}
	if m["LOCAL_SKILL_CMD_TIMEOUT_SEC"] != "300" {
		t.Fatalf("LOCAL_SKILL_CMD_TIMEOUT_SEC=%q, want 300", m["LOCAL_SKILL_CMD_TIMEOUT_SEC"])
	}

	// Unset in config: leave it to the agent's own default rather than pinning 0.
	for _, e := range h.generateSkillAgentEnvs(dac, "dac-build", `[]`, &DACConfig{}, nil) {
		if e.Name == "LOCAL_SKILL_CMD_TIMEOUT_SEC" {
			t.Fatalf("expected the env to stay unset, got %q", e.Value)
		}
	}
}

// Only the credential is exported. Provider, base URL and model belong to the
// skill's own shipped config; exporting them would decide its LLM from outside.
func TestGenerateSkillAgentEnvs_ExportsOnlyTheAPIKey(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "build"
	dac.Namespace = "default"

	m := map[string]string{}
	for _, e := range h.generateSkillAgentEnvs(dac, "dac-build", `[]`, nil, &LLMConfig{
		Provider: "openai_compatible",
		BaseURL:  "https://api.openai.com/v1",
		Model:    "gpt-5.6-luna",
		APIKey:   "sk-test",
	}) {
		m[e.Name] = e.Value
	}
	if m["TDB_LLM_API_KEY"] != "sk-test" {
		t.Fatalf("TDB_LLM_API_KEY=%q, want sk-test", m["TDB_LLM_API_KEY"])
	}
	for _, k := range []string{"TDB_LLM_PROVIDER", "TDB_LLM_BASE_URL", "TDB_LLM_MODEL"} {
		if _, ok := m[k]; ok {
			t.Fatalf("%s must not be exported: it would override the skill's own config", k)
		}
	}
}

func TestGenerateSkillAgentEnvs_NoLLMConfigLeavesTDBLLMUnset(t *testing.T) {
	h := &DataAgentContainerGenerator{}
	dac := &dacv1alpha1.DataAgentContainer{}
	dac.Name = "bare"
	dac.Namespace = "default"

	for _, e := range h.generateSkillAgentEnvs(dac, "dac-bare", `[]`, nil, nil) {
		if len(e.Name) > 8 && e.Name[:8] == "TDB_LLM_" {
			t.Fatalf("expected no TDB_LLM_* env, got %s", e.Name)
		}
	}
}
