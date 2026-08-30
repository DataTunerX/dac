package domain

import "testing"

func TestBuildTDBPipelineIdempotencyKeyUsesExplicitKey(t *testing.T) {
	req := &CreateTDBPipelineRunRequest{
		IdempotencyKey: "operator-supplied-key",
		DatasetID:      "ignored",
	}
	if got := BuildTDBPipelineIdempotencyKey(req); got != "operator-supplied-key" {
		t.Fatalf("expected the explicit key, got %q", got)
	}
}

func TestBuildTDBPipelineIdempotencyKeyIsStableForSameSourceAndTarget(t *testing.T) {
	newReq := func() *CreateTDBPipelineRunRequest {
		return &CreateTDBPipelineRunRequest{
			Source:     TDBPipelineSource{Type: TDBPipelineSourceS3, URI: "s3://archaeology-source/papers/"},
			Collection: "academic_papers",
			Target:     TDBPipelineTargetSpec{Domain: "archeology"},
		}
	}
	first := BuildTDBPipelineIdempotencyKey(newReq())
	second := BuildTDBPipelineIdempotencyKey(newReq())
	if first != second {
		t.Fatalf("expected a stable key, got %q then %q", first, second)
	}
	if first != "archaeology-source/papers/:v0:archeology:academic_papers" {
		t.Fatalf("unexpected key %q", first)
	}
}

func TestBuildTDBPipelineIdempotencyKeyChangesWithSourceVersion(t *testing.T) {
	base := CreateTDBPipelineRunRequest{
		Source:     TDBPipelineSource{Type: TDBPipelineSourceS3, URI: "s3://archaeology-source/papers/"},
		Collection: "academic_papers",
		Target:     TDBPipelineTargetSpec{Domain: "archeology"},
	}
	withVersion := base
	withVersion.SourceVersion = "etag-abc123"

	if BuildTDBPipelineIdempotencyKey(&base) == BuildTDBPipelineIdempotencyKey(&withVersion) {
		t.Fatal("expected a changed source version to produce a different key")
	}
}

func TestBuildTDBPipelineIdempotencyKeySanitizesSegments(t *testing.T) {
	req := &CreateTDBPipelineRunRequest{
		DatasetID:  "考古 论文集",
		Collection: "academic papers",
		Target:     TDBPipelineTargetSpec{Domain: "archeology"},
	}
	// Non-ASCII and spaces become "-" so the key stays a valid header value,
	// and no segment can swallow the ":" separators.
	if got := BuildTDBPipelineIdempotencyKey(req); got != "------:v0:archeology:academic-papers" {
		t.Fatalf("unexpected sanitized key %q", got)
	}
}

func TestBuildTDBPipelineIdempotencyKeyNamesPVCSources(t *testing.T) {
	req := &CreateTDBPipelineRunRequest{
		Source:     TDBPipelineSource{Type: TDBPipelineSourcePVC, ClaimName: "tdb-pipeline-work", Path: "/data/papers"},
		Collection: "academic_papers",
		Target:     TDBPipelineTargetSpec{Domain: "archeology"},
	}
	if got := BuildTDBPipelineIdempotencyKey(req); got != "tdb-pipeline-work//data/papers:v0:archeology:academic_papers" {
		t.Fatalf("unexpected pvc key %q", got)
	}
}
