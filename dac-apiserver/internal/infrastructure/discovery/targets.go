package discovery

import (
	"encoding/binary"
	"fmt"
	"net"
	"strconv"
	"strings"
)

const maxExpandedTargets = 4096

// ParseTargets parses a target spec into a list of scan targets.
//
// Supported forms:
// - single host or IP: "example.com", "10.0.0.1"
// - CIDR (IPv4 only): "10.0.0.0/24"
// - range (IPv4 only): "10.0.0.10-10.0.0.20"
// - shorthand range (IPv4 only): "10.0.0.10-20" (expands last octet)
//
// Multiple specs can be separated by commas or whitespace:
// "10.0.0.1,10.0.0.0/30 10.0.0.10-12"
func ParseTargets(spec string) ([]string, error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return nil, fmt.Errorf("target is required")
	}

	parts := splitTargets(spec)
	out := make([]string, 0, len(parts))
	seen := make(map[string]struct{}, len(parts))

	add := func(host string) error {
		host = strings.TrimSpace(host)
		if host == "" {
			return nil
		}
		if _, ok := seen[host]; ok {
			return nil
		}
		if len(out) >= maxExpandedTargets {
			return fmt.Errorf("target expands to too many IPs (max %d)", maxExpandedTargets)
		}
		seen[host] = struct{}{}
		out = append(out, host)
		return nil
	}

	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}
		expanded, err := expandOneTarget(p)
		if err != nil {
			return nil, err
		}
		for _, h := range expanded {
			if err := add(h); err != nil {
				return nil, err
			}
		}
	}

	if len(out) == 0 {
		return nil, fmt.Errorf("no valid targets")
	}
	return out, nil
}

func splitTargets(s string) []string {
	return strings.FieldsFunc(s, func(r rune) bool {
		switch r {
		case ',', ' ', '\t', '\n', '\r':
			return true
		default:
			return false
		}
	})
}

func expandOneTarget(s string) ([]string, error) {
	// CIDR
	if strings.Contains(s, "/") {
		if _, ipnet, err := net.ParseCIDR(s); err == nil && ipnet != nil {
			return expandCIDRv4(ipnet)
		}
		// If ParseCIDR fails, fall through (it might be a hostname containing '/')
	}

	// Range
	if i := strings.IndexByte(s, '-'); i >= 0 {
		left := strings.TrimSpace(s[:i])
		right := strings.TrimSpace(s[i+1:])
		// IMPORTANT: do not treat hostnames like "my-host" as a range.
		// Only interpret "-" as a range delimiter when the left side is an IPv4.
		if net.ParseIP(left).To4() == nil {
			return []string{s}, nil
		}
		// If it starts like an IP range but the end is invalid, surface error.
		return expandRangeV4(left, right)
	}

	// Single host/IP
	return []string{s}, nil
}

func expandCIDRv4(ipnet *net.IPNet) ([]string, error) {
	ip4 := ipnet.IP.To4()
	if ip4 == nil {
		return nil, fmt.Errorf("only IPv4 CIDR is supported")
	}
	ones, bits := ipnet.Mask.Size()
	if bits != 32 || ones < 0 || ones > 32 {
		return nil, fmt.Errorf("invalid CIDR mask")
	}

	base := ipToU32(ip4)
	mask := maskFromPrefix(ones)
	network := base & mask
	broadcast := network | (^mask)

	start := network
	end := broadcast

	// Common expectation: for normal subnets, skip network/broadcast.
	// For /31 and /32, include all addresses.
	total := end - start + 1
	if ones <= 30 && total >= 4 {
		start++
		end--
	}

	n := int(end - start + 1)
	if n <= 0 {
		return nil, fmt.Errorf("CIDR has no usable addresses")
	}

	out := make([]string, 0, minInt(n, 256))
	for v := start; v <= end; v++ {
		out = append(out, u32ToIPv4(v))
		if len(out) > maxExpandedTargets {
			return nil, fmt.Errorf("target expands to too many IPs (max %d)", maxExpandedTargets)
		}
	}
	return out, nil
}

func expandRangeV4(left, right string) ([]string, error) {
	if left == "" || right == "" {
		return nil, fmt.Errorf("invalid range")
	}
	startIP := net.ParseIP(left).To4()
	if startIP == nil {
		return nil, fmt.Errorf("range start must be an IPv4 address")
	}

	var endIP net.IP
	if strings.Contains(right, ".") {
		endIP = net.ParseIP(right).To4()
		if endIP == nil {
			return nil, fmt.Errorf("range end must be an IPv4 address")
		}
	} else {
		// Shorthand: last octet
		oct, err := strconv.Atoi(right)
		if err != nil || oct < 0 || oct > 255 {
			return nil, fmt.Errorf("invalid range end octet")
		}
		endIP = net.IPv4(startIP[0], startIP[1], startIP[2], byte(oct)).To4()
	}

	start := ipToU32(startIP)
	end := ipToU32(endIP)
	if end < start {
		return nil, fmt.Errorf("range end must be >= start")
	}

	n := int(end - start + 1)
	if n > maxExpandedTargets {
		return nil, fmt.Errorf("target expands to too many IPs (max %d)", maxExpandedTargets)
	}

	out := make([]string, 0, minInt(n, 256))
	for v := start; v <= end; v++ {
		out = append(out, u32ToIPv4(v))
	}
	return out, nil
}

func ipToU32(ip net.IP) uint32 {
	ip4 := ip.To4()
	return binary.BigEndian.Uint32(ip4)
}

func u32ToIPv4(v uint32) string {
	var b [4]byte
	binary.BigEndian.PutUint32(b[:], v)
	return net.IPv4(b[0], b[1], b[2], b[3]).String()
}

func maskFromPrefix(ones int) uint32 {
	if ones == 0 {
		return 0
	}
	return ^uint32(0) << (32 - ones)
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

