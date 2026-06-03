package markdownprepare

import (
	"strings"
	"testing"
)

func TestPrepare_squashedTableColonlessSeparator(t *testing.T) {
	input := "| 商品名称 | SKU | 品牌 | |---|---|---| | iPhone | SKU-001 | Apple | | Samsung | SKU-002 | Samsung |"
	out := Prepare(input)
	if strings.Count(out, "\n") < 3 {
		t.Fatalf("expected multiple lines, got:\n%s", out)
	}
	if !strings.Contains(out, "| iPhone |") || !strings.Contains(out, "| Samsung |") {
		t.Fatalf("missing rows:\n%s", out)
	}
}

func TestPrepare_squashedTableColonSeparator(t *testing.T) {
	input := "| a | b | | :--- | :--- | | r1 | v1 | | r2 | v2 |"
	out := Prepare(input)
	if strings.Count(out, "\n") < 3 {
		t.Fatalf("expected multiple lines, got:\n%s", out)
	}
}

func TestPrepare_preservesValidMultilineTable(t *testing.T) {
	input := "| H1 | H2 |\n| --- | --- |\n| a | b |"
	if Prepare(input) != input {
		t.Fatalf("multiline table changed:\n%s", Prepare(input))
	}
}

func TestPrepare_unescapesLiteralBackslashN(t *testing.T) {
	input := `| A | B |\n|---|---|\n| 1 | 2 |`
	out := Prepare(input)
	if strings.Count(out, "\n") < 2 {
		t.Fatalf("expected newlines after unescape, got:\n%s", out)
	}
}
