package handler

import (
	"strings"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"github.com/lvyanru/dac-apiserver/internal/handler/dto"
)

// TestBuildStreamDelta_ExplicitFromUpstream ensures that when chunk has ReasoningContent/Content
// set (e.g. from data-service), we use them and do not parse Text.
func TestBuildStreamDelta_ExplicitFromUpstream(t *testing.T) {
	chunk := entity.StreamChunk{ReasoningContent: "think", Content: "answer"}
	delta, next := buildStreamDelta(chunk, false)
	if delta.ReasoningContent != "think" || delta.Content != "answer" {
		t.Errorf("expected explicit think/answer, got ReasoningContent=%q Content=%q", delta.ReasoningContent, delta.Content)
	}
	if next != false {
		t.Errorf("expected contentPhase unchanged false, got %v", next)
	}
}

// TestComputeStreamDeltaLegacy_TextOnlyBackwardCompat ensures text-only chunks still use
// heuristic reasoning/content split (backward compatibility when no explicit fields).
func TestComputeStreamDeltaLegacy_TextOnlyBackwardCompat(t *testing.T) {
	contentPhase := false
	delta, next := computeStreamDeltaLegacy("step 1 plan", contentPhase)
	if delta.ReasoningContent != "step 1 plan" || delta.Content != "" {
		t.Errorf("expected reasoning only, got ReasoningContent=%q Content=%q", delta.ReasoningContent, delta.Content)
	}
	if next != false {
		t.Errorf("expected contentPhase false, got %v", next)
	}

	delta2, next2 := computeStreamDeltaLegacy("hello answer", true)
	if delta2.Content != "hello answer" || delta2.ReasoningContent != "" {
		t.Errorf("expected content only, got Content=%q ReasoningContent=%q", delta2.Content, delta2.ReasoningContent)
	}
	if next2 != true {
		t.Errorf("expected contentPhase true, got %v", next2)
	}
}

// TestComputeStreamDeltaLegacy_ContentNeverContainsDACProgress ensures that when we call
// computeStreamDeltaLegacy with chunk text (which the A2A client guarantees never contains
// [[DAC_PROGRESS]] lines), the resulting delta content is used for user-facing output.
func TestComputeStreamDeltaLegacy_ContentNeverContainsDACProgress(t *testing.T) {
	contentOnly := "user-facing reply"
	delta, _ := computeStreamDeltaLegacy(contentOnly, true)
	if delta.Content != contentOnly {
		t.Errorf("expected content %q, got %q", contentOnly, delta.Content)
	}
	if strings.Contains(delta.Content, "[[DAC_PROGRESS]]") || strings.Contains(delta.Content, "[[DAC_ANSWER]]") {
		t.Error("content delta must not contain DAC frames; they are sent via progress/answer events only")
	}
}

// TestSplitByCompletionMarker ensures completion marker splits reasoning and content.
func TestSplitByCompletionMarker(t *testing.T) {
	text := "reasoning here ✅ All tasks executed successfully\nfinal answer"
	r, a, ok := splitByCompletionMarker(text)
	if !ok {
		t.Fatal("expected split to succeed")
	}
	if !strings.Contains(r, "reasoning here") || !strings.Contains(r, "All tasks executed successfully") {
		t.Errorf("reasoning part wrong: %q", r)
	}
	if strings.TrimSpace(a) != "final answer" {
		t.Errorf("content part wrong: %q", a)
	}
}

// TestChatCompletionDelta_ProgressSeparateFromContent documents that Progress chunks
// are emitted as SSE event "progress" and never appear in ChatCompletionDelta.
// The handler emits progress when chunk.Progress != "" and content when chunk.Text != "".
func TestChatCompletionDelta_ProgressSeparateFromContent(t *testing.T) {
	// ChatCompletionDelta has Content and ReasoningContent; progress goes to a separate SSE event.
	d := dto.ChatCompletionDelta{Content: "hello", ReasoningContent: "think"}
	if d.Content != "hello" || d.ReasoningContent != "think" {
		t.Errorf("delta fields: Content=%q ReasoningContent=%q", d.Content, d.ReasoningContent)
	}
	// Progress is not a field of ChatCompletionDelta; it is sent as event type "progress".
}

// TestSSEEventTypeForChunk_Progress asserts SSE event name: EventType overrides; else from payload "event"; else "progress".
func TestSSEEventTypeForChunk_Progress(t *testing.T) {
	// Payload has "event" -> use it (data-service / A2A new events)
	chunk := entity.StreamChunk{Progress: `{"event":"routing_plan_ready"}`}
	if got := sseEventTypeForChunk(chunk); got != "routing_plan_ready" {
		t.Errorf("expected event from payload, got %q", got)
	}
	// Explicit EventType overrides payload
	chunkWithType := entity.StreamChunk{Progress: `{"event":"other"}`, EventType: "phase_change"}
	if got := sseEventTypeForChunk(chunkWithType); got != "phase_change" {
		t.Errorf("expected event type phase_change when EventType set, got %q", got)
	}
	// No event in payload -> fallback "progress"
	chunkNoEvent := entity.StreamChunk{Progress: `{"message":"ok"}`}
	if got := sseEventTypeForChunk(chunkNoEvent); got != "progress" {
		t.Errorf("expected progress when no event in payload, got %q", got)
	}
}

// TestEventNameFromProgressJSON covers parsing "event" from progress JSON for SSE event name.
func TestEventNameFromProgressJSON(t *testing.T) {
	tests := []struct {
		payload string
		want    string
	}{
		{`{"event":"routing_plan_ready"}`, "routing_plan_ready"},
		{`{"event":"phase_change","phase":"reasoning"}`, "phase_change"},
		{`{"event":""}`, ""},
		{`{}`, ""},
		{`invalid`, ""},
	}
	for _, tt := range tests {
		if got := eventNameFromProgressJSON(tt.payload); got != tt.want {
			t.Errorf("eventNameFromProgressJSON(%q) = %q, want %q", tt.payload, got, tt.want)
		}
	}
}
