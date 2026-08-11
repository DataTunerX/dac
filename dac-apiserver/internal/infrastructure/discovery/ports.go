package discovery

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// DefaultPorts returns a practical default port set for asset discovery
// when the caller omits portsSpec. Includes common enterprise services
// plus DAC sandbox fixtures (GitLab/Odoo/Saleor/Boutique/fileserver).
//
// Callers that truly need a full sweep should pass "1-65535" or "*".
func DefaultPorts() []int {
	return []int{
		22, 80, 443,
		1433, 1521, 2049, 2181, 2375, 2376, 27017, 3000, 3306,
		5000, 5432, 5433, 5434, 5672, 5900, 5984, 6379, 6443,
		8000, 8001, // fileserver / Saleor API
		8069,       // Odoo
		8080, 8081, 8443, // HTTP alts / Boutique / Trino
		8888, 8929, // Jupyter / GitLab CE (sandbox)
		9000, 9001, 9002, // MinIO API/console / Saleor dashboard
		9092, 9200, 9418, 11211,
	}
}

// AllPorts returns all valid TCP ports 1..65535.
func AllPorts() []int {
	out := make([]int, 0, 65535)
	for p := 1; p <= 65535; p++ {
		out = append(out, p)
	}
	return out
}

// ParsePortSpec parses a port spec like:
// "80,443,5432" or "1-1024" or "80,443,1000-1100" or "*" / "all"
// Returns a sorted, deduplicated list of ports.
// Empty spec returns nil (caller should use DefaultPorts).
func ParsePortSpec(spec string) ([]int, error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return nil, nil
	}
	low := strings.ToLower(spec)
	if low == "*" || low == "all" {
		return AllPorts(), nil
	}
	ports := make(map[int]struct{})
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if strings.Contains(part, "-") {
			bits := strings.SplitN(part, "-", 2)
			start, err := strconv.Atoi(strings.TrimSpace(bits[0]))
			if err != nil {
				return nil, fmt.Errorf("invalid range start %q: %w", bits[0], err)
			}
			end, err := strconv.Atoi(strings.TrimSpace(bits[1]))
			if err != nil {
				return nil, fmt.Errorf("invalid range end %q: %w", bits[1], err)
			}
			if start <= 0 || end <= 0 || start > 65535 || end > 65535 || start > end {
				return nil, fmt.Errorf("invalid range: %q", part)
			}
			for p := start; p <= end; p++ {
				ports[p] = struct{}{}
			}
			continue
		}
		p, err := strconv.Atoi(part)
		if err != nil {
			return nil, fmt.Errorf("invalid port %q: %w", part, err)
		}
		if p <= 0 || p > 65535 {
			return nil, fmt.Errorf("invalid port %d", p)
		}
		ports[p] = struct{}{}
	}
	out := make([]int, 0, len(ports))
	for p := range ports {
		out = append(out, p)
	}
	sort.Ints(out)
	return out, nil
}
