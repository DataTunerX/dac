package rbac

import "strings"

// RuleMatch reports whether an HTTP (method, path) pair satisfies a permission rule.
//
// Method semantics:
//   - "*" matches any method;
//   - otherwise the rule method must equal the request method (case-sensitive, per RFC 7231).
//
// Path semantics (matching is done on the full path without query string):
//   - "*" matches exactly one segment (a segment never contains '/');
//   - "**" matches any number of segments, including zero, up to the end of the path;
//   - any other character must match literally.
//
// This is a deliberate, smaller substitute for Casbin keyMatch2 so that permission
// rules are stored as plain data and matched consistently at request time.
func RuleMatch(r Rule, method, path string) bool {
	if r.Method != "*" {
		// Comma-separated values in the seed (e.g. "GET,POST") are expanded to
		// separate rules before this function is ever called, so equality is enough here.
		if !strings.EqualFold(r.Method, method) {
			return false
		}
	}
	return pathMatch(r.Path, path)
}

// pathMatch implements '?'-free glob matching where '*' is a single segment and
// '**' is an unrestricted suffix, using iterative matching to stay O(path×rule).
func pathMatch(pattern, path string) bool {
	return matchSegments(strings.Split(pattern, "/"), strings.Split(path, "/"))
}

func matchSegments(pattern, pathSegs []string) bool {
	pIdx, sIdx := 0, 0
	starTo, starFrom := -1, -1 // position of the last '**' seen and where it re-enters

	for sIdx < len(pathSegs) {
		if pIdx < len(pattern) {
			switch {
			case pattern[pIdx] == "**":
				// Record the backtracking point: '**' may consume any number of segments.
				starTo, starFrom = pIdx, sIdx
				pIdx++
				continue
			case pattern[pIdx] == "*":
				// Single wildcard consumes exactly one segment.
				pIdx++
				sIdx++
				continue
			case pattern[pIdx] == pathSegs[sIdx]:
				pIdx++
				sIdx++
				continue
			}
		}
		// Current comparison failed; retry by letting the last '**' consume one more segment.
		if starTo >= 0 {
			starFrom++
			pIdx = starTo + 1
			sIdx = starFrom
			continue
		}
		return false
	}
	// Tail: trailing '**' may match the empty remainder.
	for pIdx < len(pattern) && pattern[pIdx] == "**" {
		pIdx++
	}
	return pIdx == len(pattern)
}
