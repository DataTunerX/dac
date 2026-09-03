package rbac

import (
	"sort"
	"strings"
	"testing"
)

// TestFixtureRulesMatchSeederCatalog is an accuracy guard for the business
// fixture: addRolePermissionCodes installs permission rules through
// methodForCode/pathForCode, which is a hand-maintained copy of the seed
// catalog. If anyone edits seeder.go without updating those helpers, the
// matrix tests would silently test a DIFFERENT rule surface. This test
// asserts rule-for-rule equality with the real catalog.
func TestFixtureRulesMatchSeederCatalog(t *testing.T) {
	want := make(map[string][]Rule)
	for code, sp := range mergeSeedPermissions(SeedPermissions) {
		p := Permission{Code: code, HTTPMethod: sp.HTTPMethod, HTTPPath: strings.Join(sp.PathTemplates, "|")}
		rules := p.Rules()
		sort.Slice(rules, func(i, j int) bool {
			if rules[i].Method != rules[j].Method {
				return rules[i].Method < rules[j].Method
			}
			return rules[i].Path < rules[j].Path
		})
		want[code] = rules
	}

	for _, code := range allSeedCodes() {
		method, path := ruleForCode(code)
		got := Permission{Code: code, HTTPMethod: method, HTTPPath: path}.Rules()
		sort.Slice(got, func(i, j int) bool {
			if got[i].Method != got[j].Method {
				return got[i].Method < got[j].Method
			}
			return got[i].Path < got[j].Path
		})

		w := want[code]
		if len(got) != len(w) {
			t.Errorf("fixture rules for %s: %d rules, catalog has %d\n  fixture: %v\n  catalog: %v", code, len(got), len(w), got, w)
			continue
		}
		for i := range got {
			if got[i] != w[i] {
				t.Errorf("fixture rules for %s differ from catalog:\n  fixture: %v\n  catalog: %v", code, got, w)
				break
			}
		}
	}
}

// TestNegativeRowsDeniedForTheRightReason closes the accuracy hole in the
// plain deny assertions of TestPermissionMatrixFullCoverage: a denied request
// might be denied for the WRONG reason (different tenant, unknown path, missing
// membership). This test proves, for every one of the 36 codes:
//
//  1. grant ONLY that code to a fresh same-scope user → the exact matrix
//     probe is ALLOWED (the code alone is sufficient);
//  2. grant EVERY code that does NOT authorize the probe (i.e. all codes whose
//     rule surface does not cover method+path, leaving out the control set) to
//     the same user → the exact matrix probe is still DENIED.
//
// The control set S for a probe is the set of codes whose rules match
// method+path. Direction 2 asserts that no code outside S can authorize the
// probe, so a deny can only be lifted by granting a member of S. This is the
// precise "denied for the right reason" guarantee; it also tolerates the
// deliberate subclassing where a manage code covers the same probe as a read
// code (e.g. skill:manage ⊇ skill:read).
func TestNegativeRowsDeniedForTheRightReason(t *testing.T) {
	catalog := mergeSeedPermissions(SeedPermissions)

	// Same namespace mapping the real fixture uses, so namespaced paths in the
	// matrix resolve identically here.
	namespaces := func(tenant string) []string {
		switch tenant {
		case tenantFinance:
			return []string{nsFinance}
		case tenantDataEng:
			return []string{nsDataLake}
		default:
			return nil
		}
	}

	build := func(granted []string, tenant string) *Engine {
		store := newFakeStorage()
		roleID := "probe-role"
		if tenant == "" {
			store.platformRoles["probe"] = []PlatformRole{{ID: roleID, Code: "probe"}}
		} else {
			store.mu.Lock()
			store.tenantNamespaces[tenant] = namespaces(tenant)
			store.tenantRoles["probe:"+tenant] = &TenantRole{ID: roleID, TenantID: tenant, Code: "probe"}
			store.mu.Unlock()
		}
		addRolePermissionCodes(store, roleID, granted...)
		return NewEngine(store, nil)
	}

	for _, row := range permissionMatrix {
		row := row
		t.Run(row.code, func(t *testing.T) {
			tenant := row.posTenant

			// Direction 1: only the tested code → allow.
			want(t, build([]string{row.code}, tenant), "probe", tenant, row.method, row.path, true)

			// Direction 2: every other code except the control set → deny.
			// The control set is all codes (from the real catalog) whose rules
			// match the probe; it always contains the tested code itself.
			controls := make(map[string]bool)
			for code, sp := range catalog {
				p := Permission{Code: code, HTTPMethod: sp.HTTPMethod, HTTPPath: strings.Join(sp.PathTemplates, "|")}
				if p.Allows(row.method, row.path) {
					controls[code] = true
				}
			}
			others := make([]string, 0, len(catalog)-len(controls))
			for c := range catalog {
				if !controls[c] {
					others = append(others, c)
				}
			}
			if len(others) == 0 {
				t.Fatal("control set covers the whole catalog; matrix probe is not code-specific")
			}
			want(t, build(others, tenant), "probe", tenant, row.method, row.path, false)
		})
	}
}

func allSeedCodes() []string {
	seen := make(map[string]bool, len(SeedPermissions))
	for _, sp := range SeedPermissions {
		seen[sp.Code] = true
	}
	out := make([]string, 0, len(seen))
	for c := range seen {
		out = append(out, c)
	}
	sort.Strings(out)
	return out
}
