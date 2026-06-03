// Package markdownprepare normalizes LLM/API markdown before clients render with GFM.
// Mirrors frontend/src/lib/prepare-markdown.ts (transport escapes, fences, table repair).
package markdownprepare

import (
	"regexp"
	"strings"
)

var (
	leakTagBlockRE = regexp.MustCompile(`(?is)<(think|redacted_thinking|thinking)\b[^>]*>[\s\S]*?</\s*(think|redacted_thinking|thinking)\s*>`)
	leakTagOrphanRE = regexp.MustCompile(`(?i)</?\s*(think|redacted_thinking|thinking)\b[^>]*>`)
	pipePairRE             = regexp.MustCompile(`\|\s*\|`)
	pipeDashSeparatorRE    = regexp.MustCompile(`\|[\s:]*-{3,}`)
	separatorAfterPairRE   = regexp.MustCompile(`^[\s:]*-{3,}`)
	excessiveNewlinesRE = regexp.MustCompile(`\n{4,}`)
	fenceLineRE = regexp.MustCompile("(?m)^\\s*`{3}\\s*[\\w-]*\\s*$")
	tablesListRE = regexp.MustCompile(`(?i)Tables\s*[:：]`)
	tableRowRE = regexp.MustCompile(`(?i)table name:\s*([^(,，]+?)(?:\(([^)]+)\))?[,，]?\s*table description:\s*(.*)`)
)

// Prepare normalizes assistant markdown for history API responses.
func Prepare(raw string) string {
	s := stripModelLeakTags(unescapeJSONLike(raw))
	s = excessiveNewlinesRE.ReplaceAllString(s, "\n\n\n")
	s = balanceCodeFences(s)
	s = convertTablesNumberedList(s)
	return repairGfmTables(s)
}

func stripModelLeakTags(input string) string {
	if input == "" {
		return input
	}
	out := leakTagBlockRE.ReplaceAllString(input, "")
	return leakTagOrphanRE.ReplaceAllString(out, "")
}

func unescapeJSONLike(input string) string {
	r := strings.NewReplacer(
		`\n`, "\n",
		`\r`, "\r",
		`\t`, "\t",
		`\"`, `"`,
		`\\`, `\`,
	)
	return r.Replace(input)
}

func balanceCodeFences(input string) string {
	lines := strings.Split(input, "\n")
	count := 0
	for _, line := range lines {
		if fenceLineRE.MatchString(line) {
			count++
		}
	}
	if count%2 == 0 {
		return input
	}
	return strings.TrimRight(input, "\n") + "\n\n```\n"
}

func pushMappedLines(out *[]string, chunk string) {
	if strings.Contains(chunk, "\n") {
		*out = append(*out, strings.Split(chunk, "\n")...)
	} else {
		*out = append(*out, chunk)
	}
}

func mapLines(text string, fn func(line string, inFence bool) string) string {
	lines := strings.Split(text, "\n")
	inFence := false
	out := make([]string, 0, len(lines))
	for _, line := range lines {
		if strings.HasPrefix(strings.TrimLeft(line, " \t"), "```") {
			inFence = !inFence
		}
		pushMappedLines(&out, fn(line, inFence))
	}
	return strings.Join(out, "\n")
}

func parseTableCells(row string) []string {
	parts := strings.Split(row, "|")
	cells := make([]string, 0, len(parts))
	for _, p := range parts {
		cells = append(cells, strings.TrimSpace(p))
	}
	if len(cells) > 0 && cells[0] == "" {
		cells = cells[1:]
	}
	if len(cells) > 0 && cells[len(cells)-1] == "" {
		cells = cells[:len(cells)-1]
	}
	return cells
}

func isSeparatorLine(line string) bool {
	t := strings.TrimSpace(line)
	if !strings.Contains(t, "|") || !strings.Contains(t, "-") {
		return false
	}
	for _, r := range t {
		switch r {
		case '|', ':', '-', ' ':
		default:
			return false
		}
	}
	return true
}

func lineLooksLikeSquashedTable(line string) bool {
	if !strings.Contains(line, "|") {
		return false
	}
	if isSeparatorLine(line) || pipeDashSeparatorRE.MatchString(line) {
		return true
	}
	pipeCount := strings.Count(line, "|")
	return pipeCount >= 6 && hasSquashedRowBoundary(line)
}

// hasSquashedRowBoundary detects `| |` joins between GFM rows (no regexp lookahead).
func hasSquashedRowBoundary(line string) bool {
	for _, loc := range pipePairRE.FindAllStringIndex(line, -1) {
		if shouldSplitAtPipePair(line, loc[1]) {
			return true
		}
	}
	return false
}

func shouldSplitAtPipePair(line string, after int) bool {
	rest := strings.TrimLeft(line[after:], " \t")
	if rest == "" {
		return false
	}
	if separatorAfterPairRE.MatchString(rest) {
		return true
	}
	for _, r := range rest {
		if r != ' ' && r != '\t' && r != '\n' {
			return true
		}
	}
	return false
}

func replaceSquashedRowBoundaries(line string) string {
	locs := pipePairRE.FindAllStringIndex(line, -1)
	if len(locs) == 0 {
		return line
	}
	var b strings.Builder
	last := 0
	for _, loc := range locs {
		if !shouldSplitAtPipePair(line, loc[1]) {
			continue
		}
		b.WriteString(line[last:loc[0]])
		b.WriteString("|\n|")
		last = loc[1]
	}
	b.WriteString(line[last:])
	return b.String()
}

func alignSeparatorToHeader(table string) string {
	rows := make([]string, 0)
	for _, l := range strings.Split(table, "\n") {
		if strings.TrimSpace(l) != "" {
			rows = append(rows, l)
		}
	}
	if len(rows) < 2 {
		return table
	}
	headerCols := len(parseTableCells(rows[0]))
	sepCols := len(parseTableCells(rows[1]))
	if headerCols > 0 && sepCols > 0 && sepCols != headerCols {
		parts := make([]string, headerCols)
		for i := range parts {
			parts[i] = ":---"
		}
		rows[1] = "| " + strings.Join(parts, " | ") + " |"
	}
	return strings.Join(rows, "\n")
}

func expandSquashedTableLine(line string) string {
	firstPipe := strings.Index(line, "|")
	if firstPipe < 0 {
		return line
	}
	prefix := strings.TrimRight(line[:firstPipe], " \t")
	table := strings.TrimSpace(line[firstPipe:])
	table = replaceSquashedRowBoundaries(table)
	tableLines := strings.Split(table, "\n")
	for i, l := range tableLines {
		t := strings.TrimSpace(l)
		if !strings.HasPrefix(t, "|") {
			tableLines[i] = "| " + t
		} else {
			tableLines[i] = t
		}
	}
	table = alignSeparatorToHeader(strings.Join(tableLines, "\n"))
	if prefix != "" {
		return prefix + "\n\n" + table
	}
	return table
}

func convertTablesNumberedList(text string) string {
	lines := strings.Split(text, "\n")
	out := make([]string, 0, len(lines))
	inFence := false
	isFence := func(line string) bool { return strings.HasPrefix(strings.TrimLeft(line, " \t"), "```") }
	numberedRE := regexp.MustCompile(`^\s*\d+\.\s+`)

	for i := 0; i < len(lines); i++ {
		line := lines[i]
		if isFence(line) {
			inFence = !inFence
		}
		if !inFence && tablesListRE.MatchString(line) {
			type row struct{ name, entity, desc string }
			var rows []row
			j := i + 1
			for j < len(lines) && numberedRE.MatchString(lines[j]) {
				body := strings.TrimSpace(numberedRE.ReplaceAllString(lines[j], ""))
				if m := tableRowRE.FindStringSubmatch(body); m != nil {
					rows = append(rows, row{
						name:   strings.TrimSpace(m[1]),
						entity: strings.TrimSpace(m[2]),
						desc:   strings.TrimSpace(m[3]),
					})
				}
				j++
			}
			if len(rows) > 0 {
				loc := tablesListRE.FindStringIndex(line)
				if loc != nil && loc[0] > 0 {
					out = append(out, strings.TrimRight(line[:loc[0]], " \t"))
				}
				out = append(out, "", "**Tables**", "", "| Table | Description |", "| :--- | :--- |")
				for _, r := range rows {
					label := r.name
					if r.entity != "" {
						label = r.name + " (" + r.entity + ")"
					}
					out = append(out, "| "+escPipe(label)+" | "+escPipe(r.desc)+" |")
				}
				out = append(out, "")
				i = j - 1
				continue
			}
		}
		out = append(out, line)
	}
	return strings.Join(out, "\n")
}

func escPipe(v string) string {
	return strings.ReplaceAll(strings.TrimSpace(v), "|", "\\|")
}

func ensureBlankLineBeforeTables(text string) string {
	lines := strings.Split(text, "\n")
	out := make([]string, 0, len(lines)+4)
	inFence := false
	isFence := func(line string) bool { return strings.HasPrefix(strings.TrimLeft(line, " \t"), "```") }

	for i := 0; i < len(lines); i++ {
		line := lines[i]
		next := ""
		if i+1 < len(lines) {
			next = lines[i+1]
		}
		if isFence(line) {
			inFence = !inFence
		}
		isTableHeader := !inFence && strings.Contains(line, "|") && isSeparatorLine(next)
		if len(out) > 0 && isTableHeader && strings.TrimSpace(out[len(out)-1]) != "" {
			out = append(out, "")
		}
		out = append(out, line)
	}
	return strings.Join(out, "\n")
}

func repairGfmTables(text string) string {
	expanded := mapLines(text, func(line string, inFence bool) string {
		if inFence || !lineLooksLikeSquashedTable(line) {
			return line
		}
		return expandSquashedTableLine(line)
	})
	return ensureBlankLineBeforeTables(expanded)
}
