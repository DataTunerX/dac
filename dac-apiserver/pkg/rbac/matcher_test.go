package rbac

import "testing"

// TestRuleMatchSingleSegment verifies that a single '*' wildcard matches exactly
// one path segment and does not span slashes (matching the old keyMatch2 contract).
func TestRuleMatchSingleSegment(t *testing.T) {
	cases := []struct {
		rule   Rule
		method string
		path   string
		want   bool
	}{
		{Rule{"GET", "/api/v1/namespaces/*/agents"}, "GET", "/api/v1/namespaces/dev/agents", true},
		{Rule{"GET", "/api/v1/namespaces/*/agents"}, "GET", "/api/v1/namespaces/dev/prod/agents", false}, // '*' must not cross '/'
		{Rule{"GET", "/api/v1/namespaces/*/agents"}, "POST", "/api/v1/namespaces/dev/agents", false},     // wrong method
		{Rule{"*", "/api/v1/namespaces/*/agents"}, "DELETE", "/api/v1/namespaces/dev/agents", true},      // any method
		{Rule{"GET", "/api/v1/agents"}, "GET", "/api/v1/agents", true},
		{Rule{"GET", "/api/v1/agents"}, "GET", "/api/v1/agents/extra", false}, // exact path, no wildcard
	}
	for _, tc := range cases {
		if got := RuleMatch(tc.rule, tc.method, tc.path); got != tc.want {
			t.Errorf("RuleMatch(%+v, %s, %s) = %v, want %v", tc.rule, tc.method, tc.path, got, tc.want)
		}
	}
}

// TestRuleMatchDoubleStar verifies '**' matches an arbitrary suffix of the path.
func TestRuleMatchDoubleStar(t *testing.T) {
	cases := []struct {
		rule Rule
		path string
		want bool
	}{
		{Rule{"*", "/api/v1/system/configurations/**"}, "/api/v1/system/configurations", true}, // zero segments
		{Rule{"*", "/api/v1/system/configurations/**"}, "/api/v1/system/configurations/dac/versions", true},
		{Rule{"*", "/api/v1/system/configurations/**"}, "/api/v1/system/other", false},
		{Rule{"GET", "/api/v1/semantic-groups/**"}, "/api/v1/semantic-groups", true},
		{Rule{"GET", "/api/v1/semantic-groups/**"}, "/api/v1/semantic-groups/1/members", true},
	}
	for _, tc := range cases {
		if got := RuleMatch(tc.rule, tc.rule.Method, tc.path); got != tc.want {
			t.Errorf("RuleMatch(%+v, %s) = %v, want %v", tc.rule, tc.path, got, tc.want)
		}
	}
}

// TestPermissionRulesExpansion verifies a comma-separated method list expands
// into one rule per method, keeping the '*' and path intact.
func TestPermissionRulesExpansion(t *testing.T) {
	p := Permission{
		Code:       "llmconfig:manage",
		HTTPMethod: "GET,PUT,DELETE",
		HTTPPath:   "/api/v1/namespaces/*/llm-configmaps/*",
	}
	rules := p.Rules()
	if len(rules) != 3 {
		t.Fatalf("Rules() = %d rules, want 3", len(rules))
	}
	for _, r := range rules {
		if !RuleMatch(r, r.Method, "/api/v1/namespaces/default/llm-configmaps/llm") {
			t.Errorf("rule %+v should match its own method/path", r)
		}
	}
}
