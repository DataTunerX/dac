package discovery

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

func DefaultPorts() []int {
	// Small but useful defaults; user can override with portsSpec.
	// Include DAC sandbox common ports (GitLab/Odoo + multiple Postgres).
	return []int{
		22, 80, 443,
		3306, // mysql/mariadb
		5432, 5433, 5434, // postgres (main/metastore/odoo)
		6379, // redis
		8069, // odoo
		8080, // trino
		8929, // gitlab (sandbox custom port)
		9000, 9001, // minio api/console
		9083, // hive metastore thrift
	}
}

// AllPorts returns all valid TCP ports 1..65535.
// NOTE: This is potentially heavy; use with appropriate timeout/concurrency.
func AllPorts() []int {
	out := make([]int, 0, 65535)
	for p := 1; p <= 65535; p++ {
		out = append(out, p)
	}
	return out
}

// ParsePortSpec parses a port spec like:
// "80,443,5432" or "1-1024" or "80,443,1000-1100"
// Returns a sorted, deduplicated list of ports.
func ParsePortSpec(spec string) ([]int, error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return nil, nil
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

