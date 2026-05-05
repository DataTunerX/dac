package probe

import (
	"errors"
	"io"
	"testing"

	"github.com/go-sql-driver/mysql"
	"github.com/lib/pq"

	"github.com/lvyanru/dac-apiserver/internal/domain"
)

func TestMapMySQLError(t *testing.T) {
	tests := []struct {
		name      string
		in        error
		wantNil   bool
		wantErrIs error
	}{
		{"nil passes through", nil, true, nil},
		{"access denied -> invalid input", &mysql.MySQLError{Number: 1045}, false, domain.ErrInvalidInput},
		{"no privilege -> invalid input", &mysql.MySQLError{Number: 1142}, false, domain.ErrInvalidInput},
		{"unknown db -> invalid input", &mysql.MySQLError{Number: 1049}, false, domain.ErrInvalidInput},
		{"other mysql error -> internal", &mysql.MySQLError{Number: 9999}, false, domain.ErrInternal},
		{"non-driver error -> internal", io.EOF, false, domain.ErrInternal},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := mapMySQLError(tc.in)
			if tc.wantNil {
				if got != nil {
					t.Fatalf("got %v want nil", got)
				}
				return
			}
			if !errors.Is(got, tc.wantErrIs) {
				t.Fatalf("err=%v want errors.Is(_, %v)", got, tc.wantErrIs)
			}
		})
	}
}

func TestMapPostgresError(t *testing.T) {
	tests := []struct {
		name      string
		in        error
		wantNil   bool
		wantErrIs error
	}{
		{"nil passes through", nil, true, nil},
		{"invalid password -> invalid input", &pq.Error{Code: "28P01"}, false, domain.ErrInvalidInput},
		{"invalid auth spec -> invalid input", &pq.Error{Code: "28000"}, false, domain.ErrInvalidInput},
		{"invalid catalog -> invalid input", &pq.Error{Code: "3D000"}, false, domain.ErrInvalidInput},
		{"other pq error -> internal", &pq.Error{Code: "53300"}, false, domain.ErrInternal},
		{"non-driver error -> internal", io.EOF, false, domain.ErrInternal},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := mapPostgresError(tc.in)
			if tc.wantNil {
				if got != nil {
					t.Fatalf("got %v want nil", got)
				}
				return
			}
			if !errors.Is(got, tc.wantErrIs) {
				t.Fatalf("err=%v want errors.Is(_, %v)", got, tc.wantErrIs)
			}
		})
	}
}
