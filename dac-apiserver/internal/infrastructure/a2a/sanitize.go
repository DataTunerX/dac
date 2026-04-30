package a2a

import "regexp"

// Some downstream agents append an internal validation marker to indicate the
// final answer is good (e.g. "reason: The current answer addresses the question
// very well."). It is meant for agent-to-agent coordination and must not leak
// into the user-facing answer. We strip it as close to the network boundary as
// possible so both the SSE stream and the persisted history stay clean.
//
// The pattern intentionally consumes one optional surrounding newline on each
// side so removing the marker line does not leave a stray blank line behind.
var successMarkerRE = regexp.MustCompile(
	`(?i)\r?\n?[ \t]*reason:[ \t]*The current answer addresses the question very well\.[ \t]*\r?\n?`,
)

// excessiveBlankLinesRE collapses 3+ consecutive newlines that may appear when
// the marker sat between two already-blank lines.
var excessiveBlankLinesRE = regexp.MustCompile(`\n{3,}`)

// stripSuccessMarker removes the internal validation marker from a piece of
// user-facing text. Safe to call on empty strings.
func stripSuccessMarker(text string) string {
	if text == "" {
		return text
	}
	cleaned := successMarkerRE.ReplaceAllString(text, "")
	if cleaned == text {
		return text
	}
	return excessiveBlankLinesRE.ReplaceAllString(cleaned, "\n\n")
}
