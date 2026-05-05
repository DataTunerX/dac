package probe

import (
	"context"
	"reflect"
	"sync"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

// fakeProber is a minimal domain.Prober used to drive Registry tests
// without touching real database drivers.
type fakeProber struct{ t string }

func (f *fakeProber) Type() string { return f.t }
func (f *fakeProber) Probe(context.Context, domain.ConnectionTarget) (*domain.ProbeResult, error) {
	return &domain.ProbeResult{}, nil
}

func TestRegistry_GetIsCaseInsensitiveAndTrimmed(t *testing.T) {
	r := NewRegistry(&fakeProber{t: "MySQL"}, &fakeProber{t: "postgres"})

	cases := []struct {
		name    string
		query   string
		wantOk  bool
		wantTyp string
	}{
		{"exact lowercase", "mysql", true, "MySQL"},
		{"upper case input", "MYSQL", true, "MySQL"},
		{"whitespace tolerated", "  postgres  ", true, "postgres"},
		{"unknown returns miss", "oracle", false, ""},
		{"empty returns miss", "", false, ""},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, ok := r.Get(tc.query)
			if ok != tc.wantOk {
				t.Fatalf("ok=%v want %v", ok, tc.wantOk)
			}
			if !ok {
				return
			}
			if got.Type() != tc.wantTyp {
				t.Fatalf("type=%q want %q", got.Type(), tc.wantTyp)
			}
		})
	}
}

func TestRegistry_SupportedReturnsSortedNormalizedKeys(t *testing.T) {
	r := NewRegistry(&fakeProber{t: "Postgres"}, &fakeProber{t: "mysql"})
	got := r.Supported()
	want := []string{"mysql", "postgres"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("supported=%v want %v", got, want)
	}
}

func TestRegistry_DuplicateRegistrationPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatal("expected panic on duplicate registration")
		}
	}()
	NewRegistry(&fakeProber{t: "mysql"}, &fakeProber{t: "MYSQL"})
}

func TestRegistry_EmptyTypePanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatal("expected panic on empty type registration")
		}
	}()
	NewRegistry(&fakeProber{t: "  "})
}

func TestRegistry_ConcurrentReadsAreSafe(t *testing.T) {
	r := NewRegistry(&fakeProber{t: "mysql"}, &fakeProber{t: "postgres"})

	var wg sync.WaitGroup
	for i := 0; i < 64; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _ = r.Get("mysql")
			_ = r.Supported()
		}()
	}
	wg.Wait()
}
