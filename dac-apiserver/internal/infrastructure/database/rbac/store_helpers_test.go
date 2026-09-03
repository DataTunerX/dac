package rbac

import (
	"errors"
	"testing"

	"github.com/google/uuid"

	domain "github.com/lvyanru/dac-apiserver/internal/domain"
	eng "github.com/lvyanru/dac-apiserver/pkg/rbac"
)

// These tests cover the store's pure helpers (parse / classify), which do not
// require a live database. The ent-backed CRUD paths are exercised through the
// in-memory fakes in the usecase and engine packages; launching sqlite here is
// not possible in sandboxed CI without network access to the sqlite driver.

func TestMustParseUUID(t *testing.T) {
	id := uuid.New().String()
	got, err := mustParseUUID(id)
	if err != nil {
		t.Fatalf("parse valid uuid: %v", err)
	}
	if got.String() != id {
		t.Fatalf("got %s, want %s", got, id)
	}

	if _, err := mustParseUUID("not-a-uuid"); err == nil {
		t.Fatal("invalid uuid must fail")
	}
	if _, err := mustParseUUID(""); err == nil {
		t.Fatal("empty uuid must fail")
	}
}

func TestIsEntNotFoundAndWrap(t *testing.T) {
	if isEntNotFound(nil) {
		t.Fatal("nil must not be not-found")
	}
	if isEntNotFound(errors.New("boom")) {
		t.Fatal("unrelated error must not be treated as ent-not-found")
	}
	if isEntNotFound(domain.ErrNotFound) {
		t.Fatal("the domain sentinel alone must not masquerade as an ent not-found")
	}
}

func TestWrapsErrNotFoundRoundTripsSentinels(t *testing.T) {
	// wrapsErrNotFound only rewrites ent not-found errors into the shared
	// sentinel; every other error passes through untouched.
	err := errors.New("boom")
	if got := wrapsErrNotFound(err); got != err {
		t.Fatalf("non-not-found error must pass through, got %v", got)
	}
}

func TestRBErrNotFoundSatisfiesBothSentinels(t *testing.T) {
	if !errors.Is(rbErrNotFound, eng.ErrNotFound) {
		t.Fatal("rbErrNotFound must wrap the engine sentinel")
	}
	if !errors.Is(rbErrNotFound, domain.ErrNotFound) {
		t.Fatal("rbErrNotFound must wrap the domain sentinel")
	}
	if !domain.IsNotFound(rbErrNotFound) {
		t.Fatal("domain.IsNotFound(rbErrNotFound) must be true")
	}
}

func TestStrPtrNilForEmpty(t *testing.T) {
	if p := strPtr(""); p != nil {
		t.Fatalf("empty string must yield nil, got %v", *p)
	}
	if p := strPtr("x"); p == nil || *p != "x" {
		t.Fatal("non-empty string must yield a pointer to the value")
	}
}