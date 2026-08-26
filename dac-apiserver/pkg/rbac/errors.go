package rbac

import "errors"

// ErrNotFound is the sentinel marking "the requested RBAC record does not exist"
// as opposed to a storage/infrastructure failure. Storage implementations wrap
// their not-found results with this sentinel so the engine and usecases can
// apply deny-by-default without surfacing missing rows as 5xx errors.
var ErrNotFound = errors.New("rbac record not found")

// errNotFound is the unexported alias used internally by the engine. Storage
// implementations should wrap ErrNotFound; both resolve via errors.Is.
var errNotFound = ErrNotFound

// isNotFound reports whether err signals a missing record rather than a failure.
func isNotFound(err error) bool {
	return err != nil && errors.Is(err, ErrNotFound)
}
