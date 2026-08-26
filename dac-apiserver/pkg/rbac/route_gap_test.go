package rbac

import (
	"fmt"
	"strings"
	"testing"
)

// routeTable lists every protected route from internal/router/router.go,
// with :params replaced by representative concrete values.
var routeTable = []struct {
	method string
	path   string
	note   string
}{
	// namespaces / environment
	{"GET", "/api/v1/namespaces", "namespace list"},
	{"GET", "/api/v1/environment/gpu", "gpu availability"},
	// users
	{"GET", "/api/v1/users/me", "self"},
	{"GET", "/api/v1/users", "list users"},
	{"GET", "/api/v1/users/u1", "get user"},
	{"DELETE", "/api/v1/users/u1", "delete user"},
	// rbac management
	{"GET", "/api/v1/rbac/permissions", "permissions"},
	{"GET", "/api/v1/rbac/me/tenants", "my tenants"},
	{"GET", "/api/v1/rbac/tenants", "list tenants"},
	{"POST", "/api/v1/rbac/tenants", "create tenant"},
	{"GET", "/api/v1/rbac/tenants/t1", "get tenant"},
	{"PUT", "/api/v1/rbac/tenants/t1", "update tenant"},
	{"DELETE", "/api/v1/rbac/tenants/t1", "delete tenant"},
	{"POST", "/api/v1/rbac/tenants/t1/disable", "disable tenant"},
	{"POST", "/api/v1/rbac/tenants/t1/enable", "enable tenant"},
	{"GET", "/api/v1/rbac/tenants/t1/namespaces", "ns list"},
	{"POST", "/api/v1/rbac/tenants/t1/namespaces", "add ns"},
	{"DELETE", "/api/v1/rbac/tenants/t1/namespaces/dev", "remove ns"},
	{"GET", "/api/v1/rbac/tenants/t1/roles", "list roles"},
	{"POST", "/api/v1/rbac/tenants/t1/roles", "create role"},
	{"PUT", "/api/v1/rbac/tenants/t1/roles/r1", "update role"},
	{"DELETE", "/api/v1/rbac/tenants/t1/roles/r1", "del role"},
	{"PUT", "/api/v1/rbac/tenants/t1/roles/r1/permissions", "set role perms"},
	{"GET", "/api/v1/rbac/tenants/t1/users", "list members"},
	{"POST", "/api/v1/rbac/tenants/t1/users", "add member"},
	{"PUT", "/api/v1/rbac/tenants/t1/users/u1/role", "change member role"},
	{"DELETE", "/api/v1/rbac/tenants/t1/users/u1", "remove member"},
	{"GET", "/api/v1/rbac/platform/roles", "list platform roles"},
	{"POST", "/api/v1/rbac/platform/roles", "create platform role"},
	{"PUT", "/api/v1/rbac/platform/roles/pr1", "update platform role"},
	{"DELETE", "/api/v1/rbac/platform/roles/pr1", "del platform role"},
	{"PUT", "/api/v1/rbac/platform/roles/pr1/permissions", "set platform perms"},
	{"GET", "/api/v1/rbac/platform/roles/pr1/users", "platform role users"},
	{"POST", "/api/v1/rbac/platform/users", "grant platform role"},
	{"DELETE", "/api/v1/rbac/platform/users/u1/roles/pr1", "revoke platform role"},
	// agents
	{"GET", "/api/v1/agents", "list all agents"},
	{"POST", "/api/v1/namespaces/dev/agents", "create agent"},
	{"GET", "/api/v1/namespaces/dev/agents", "list agents"},
	{"GET", "/api/v1/namespaces/dev/agents/web", "get agent"},
	{"PUT", "/api/v1/namespaces/dev/agents/web", "update agent"},
	{"DELETE", "/api/v1/namespaces/dev/agents/web", "delete agent"},
	// descriptors
	{"GET", "/api/v1/descriptors", "list all descriptors"},
	{"POST", "/api/v1/namespaces/dev/descriptors", "create descriptor"},
	{"GET", "/api/v1/namespaces/dev/descriptors", "list descriptors"},
	{"GET", "/api/v1/namespaces/dev/descriptors/dd1", "get descriptor"},
	{"GET", "/api/v1/namespaces/dev/descriptors/dd1/signature", "signature"},
	{"GET", "/api/v1/namespaces/dev/descriptors/dd1/semantic-domain", "semantic-domain"},
	{"PUT", "/api/v1/namespaces/dev/descriptors/dd1", "update descriptor"},
	{"POST", "/api/v1/namespaces/dev/descriptors/dd1/resync", "resync"},
	{"DELETE", "/api/v1/namespaces/dev/descriptors/dd1", "delete descriptor"},
	{"GET", "/api/v1/namespaces/dev/descriptors/dd1/knowledge", "get knowledge"},
	{"POST", "/api/v1/namespaces/dev/descriptors/dd1/knowledge/search", "search knowledge"},
	{"POST", "/api/v1/namespaces/dev/descriptors/dd1/knowledge/delete", "delete knowledge"},
	// configmaps
	{"POST", "/api/v1/namespaces/dev/llm-configmaps", "create llm cm"},
	{"GET", "/api/v1/namespaces/dev/llm-configmaps", "list llm cm"},
	{"GET", "/api/v1/namespaces/dev/llm-configmaps/cm1", "get llm cm"},
	{"PUT", "/api/v1/namespaces/dev/llm-configmaps/cm1", "update llm cm"},
	{"DELETE", "/api/v1/namespaces/dev/llm-configmaps/cm1", "delete llm cm"},
	{"POST", "/api/v1/namespaces/dev/prompt-configmaps", "create prompt cm"},
	{"GET", "/api/v1/namespaces/dev/prompt-configmaps", "list prompt cm"},
	{"GET", "/api/v1/namespaces/dev/prompt-configmaps/cm1", "get prompt cm"},
	{"PUT", "/api/v1/namespaces/dev/prompt-configmaps/cm1", "update prompt cm"},
	{"DELETE", "/api/v1/namespaces/dev/prompt-configmaps/cm1", "delete prompt cm"},
	// system config
	{"GET", "/api/v1/system/configurations", "list syscfg"},
	{"GET", "/api/v1/system/configurations/dac/versions/v1", "get version"},
	{"GET", "/api/v1/system/configurations/dac/versions", "list versions"},
	{"GET", "/api/v1/system/configurations/dac", "get syscfg"},
	{"PUT", "/api/v1/system/configurations/dac", "update syscfg"},
	// observability
	{"GET", "/api/v1/observability/agent-registries", "registries"},
	{"GET", "/api/v1/observability/agent-registries/r1/agents", "reg agents"},
	// semantic domains (data-services)
	{"POST", "/api/v1/semantic-domains", "create sd"},
	{"POST", "/api/v1/semantic-domains/batch", "batch create sd"},
	{"POST", "/api/v1/semantic-domains/search/by-dd", "search sd"},
	{"GET", "/api/v1/semantic-domains/status/count", "count sd"},
	{"GET", "/api/v1/semantic-domains/sd1", "get sd"},
	{"GET", "/api/v1/semantic-domains/sd1/exists", "exists sd"},
	{"PUT", "/api/v1/semantic-domains/sd1", "update sd"},
	{"DELETE", "/api/v1/semantic-domains/sd1", "delete sd"},
	{"DELETE", "/api/v1/semantic-domains/dd-info/dev/dd1", "delete sd by dd"},
	{"GET", "/api/v1/semantic-domains/dd-info/dev/dd1/exists", "exists by dd"},
	// skills
	{"POST", "/api/v1/skills/reload", "reload skills"},
	{"GET", "/api/v1/skills/namespaces", "list skill ns"},
	{"POST", "/api/v1/skills/namespaces", "create skill ns"},
	{"GET", "/api/v1/skills/namespaces/sh/exists", "ns exists"},
	{"DELETE", "/api/v1/skills/namespaces/sh", "delete skill ns"},
	{"GET", "/api/v1/skills/namespaces/sh/skills", "list skills"},
	{"POST", "/api/v1/skills/namespaces/sh/skills/create", "create skill"},
	{"POST", "/api/v1/skills/namespaces/sh/skills", "upload skill"},
	{"GET", "/api/v1/skills/namespaces/sh/skills/s1", "get skill"},
	{"POST", "/api/v1/skills/namespaces/sh/skills/s1/update", "update skill"},
	{"GET", "/api/v1/skills/namespaces/sh/skills/s1/download", "download skill"},
	{"DELETE", "/api/v1/skills/namespaces/sh/skills/s1", "delete skill"},
	// chat
	{"GET", "/api/v1/chat/conversations", "list conversations"},
	{"GET", "/api/v1/chat/conversations/run1", "get conversation"},
	// discovery
	{"POST", "/api/v1/discovery/scans", "start scan"},
	{"GET", "/api/v1/discovery/scans", "list scans"},
	{"GET", "/api/v1/discovery/scans/s1", "get scan"},
	{"PATCH", "/api/v1/discovery/scans/s1", "update scan"},
	{"DELETE", "/api/v1/discovery/scans/s1", "delete scan"},
	// datasources
	{"POST", "/api/v1/datasources/probe", "probe"},
	{"GET", "/api/v1/datasources/probe/types", "probe types"},
	// semantic groups
	{"POST", "/api/v1/semantic-groups", "create sg"},
	{"POST", "/api/v1/semantic-groups/batch", "batch sg"},
	{"GET", "/api/v1/semantic-groups", "list sg"},
	{"GET", "/api/v1/semantic-groups/roots", "roots sg"},
	{"GET", "/api/v1/semantic-groups/member-tasks/t1", "member task"},
	{"GET", "/api/v1/semantic-groups/status/count", "sg count"},
	{"GET", "/api/v1/semantic-groups/sg1/with-members", "sg with members"},
	{"GET", "/api/v1/semantic-groups/sg1", "get sg"},
	{"GET", "/api/v1/semantic-groups/sg1/exists", "sg exists"},
	{"PUT", "/api/v1/semantic-groups/sg1", "update sg"},
	{"DELETE", "/api/v1/semantic-groups/sg1", "delete sg"},
	{"POST", "/api/v1/semantic-groups/sg1/members", "add sg member"},
	{"POST", "/api/v1/semantic-groups/sg1/members/remove", "remove sg member"},
	// dd-group-relations
	{"GET", "/api/v1/dd-group-relations/group/g1", "list by group"},
	{"GET", "/api/v1/dd-group-relations/sd/sd1", "list by sd"},
	{"DELETE", "/api/v1/dd-group-relations/rel1", "delete relation"},
	// knowledge graph
	{"POST", "/api/v1/knowledge-graph/add-with-source", "kg add"},
	{"POST", "/api/v1/knowledge-graph/search-with-source", "kg search"},
	{"POST", "/api/v1/knowledge-graph/get-graph-by-source", "kg get graph"},
	{"DELETE", "/api/v1/knowledge-graph/delete-with-source", "kg delete"},
	// chat completions
	{"POST", "/v1/chat/completions", "chat completion"},
}

// TestRouteGapAnalysis checks every protected route from router.go against the
// merged seed permission catalog and reports which routes have NO rule.
func TestRouteGapAnalysis(t *testing.T) {
	merged := mergeSeedPermissions(SeedPermissions)

	// Build one rule bank per code.
	type ruleBank struct {
		code  string
		rules []Rule
	}
	var banks []ruleBank
	for code, sp := range merged {
		p := Permission{Code: code, HTTPMethod: sp.HTTPMethod, HTTPPath: strings.Join(sp.PathTemplates, "|")}
		banks = append(banks, ruleBank{code: code, rules: p.Rules()})
	}

	covered := 0
	var gaps []string
	for _, rt := range routeTable {
		ok := false
		for _, bank := range banks {
			for _, r := range bank.rules {
				if RuleMatch(r, rt.method, rt.path) {
					ok = true
				}
			}
		}
		if ok {
			covered++
		} else {
			gaps = append(gaps, fmt.Sprintf("%-7s %-70s  (%-25s)", rt.method, rt.path, rt.note))
		}
	}
	t.Logf("covered=%d/%d", covered, len(routeTable))
	for _, g := range gaps {
		t.Logf("  GAP %s", g)
	}
}

// ---- local clone of internal/usecase/rbac.mergeSeedPermissions for analysis ----

type mergedSeedLookup struct {
	HTTPMethod    string
	PathTemplates []string
}

func mergeSeedPermissions(catalog []SeedPermission) map[string]mergedSeedLookup {
	merged := make(map[string]mergedSeedLookup, len(catalog))
	for _, sp := range catalog {
		acc, ok := merged[sp.Code]
		if sp.HTTPMethod == "*" {
			acc.HTTPMethod = "*"
		} else if !ok {
			acc.HTTPMethod = sp.HTTPMethod
		}
		acc.PathTemplates = appendUniqueT(acc.PathTemplates, strings.Split(sp.HTTPPath, "|")...)
		merged[sp.Code] = acc
	}
	return merged
}

func appendUniqueT(list []string, items ...string) []string {
	for _, it := range items {
		if it == "" {
			continue
		}
		seen := false
		for _, x := range list {
			if x == it {
				seen = true
				break
			}
		}
		if !seen {
			list = append(list, it)
		}
	}
	return list
}
