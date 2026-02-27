package discovery

import "testing"

func TestParseTargets_SingleHostOrIP(t *testing.T) {
	got, err := ParseTargets("example.com")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 1 || got[0] != "example.com" {
		t.Fatalf("unexpected result: %#v", got)
	}
}

func TestParseTargets_HostnameWithHyphen(t *testing.T) {
	got, err := ParseTargets("my-host")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 1 || got[0] != "my-host" {
		t.Fatalf("unexpected result: %#v", got)
	}
}

func TestParseTargets_List(t *testing.T) {
	got, err := ParseTargets("10.0.0.1, 10.0.0.2\t10.0.0.3\n10.0.0.1")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("unexpected len: %d %#v", len(got), got)
	}
}

func TestParseTargets_CIDR30_SkipsNetworkBroadcast(t *testing.T) {
	got, err := ParseTargets("192.168.0.0/30")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := []string{"192.168.0.1", "192.168.0.2"}
	if len(got) != len(want) {
		t.Fatalf("unexpected result: %#v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("unexpected result: %#v", got)
		}
	}
}

func TestParseTargets_CIDR31_IncludesBoth(t *testing.T) {
	got, err := ParseTargets("192.168.0.0/31")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := []string{"192.168.0.0", "192.168.0.1"}
	if len(got) != len(want) {
		t.Fatalf("unexpected result: %#v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("unexpected result: %#v", got)
		}
	}
}

func TestParseTargets_RangeFull(t *testing.T) {
	got, err := ParseTargets("10.0.0.10-10.0.0.12")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := []string{"10.0.0.10", "10.0.0.11", "10.0.0.12"}
	if len(got) != len(want) {
		t.Fatalf("unexpected result: %#v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("unexpected result: %#v", got)
		}
	}
}

func TestParseTargets_RangeShorthand(t *testing.T) {
	got, err := ParseTargets("10.0.0.10-12")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 3 || got[0] != "10.0.0.10" || got[2] != "10.0.0.12" {
		t.Fatalf("unexpected result: %#v", got)
	}
}

func TestParseTargets_InvalidRange(t *testing.T) {
	_, err := ParseTargets("10.0.0.12-10.0.0.10")
	if err == nil {
		t.Fatalf("expected error")
	}
}

func TestParseTargets_TooMany(t *testing.T) {
	_, err := ParseTargets("10.0.0.0/8")
	if err == nil {
		t.Fatalf("expected error")
	}
}

