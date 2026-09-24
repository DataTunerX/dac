package a2a

import (
	"log/slog"
	"strings"
	"testing"

	"github.com/lvyanru/dac-apiserver/internal/domain/entity"
	"trpc.group/trpc-go/trpc-a2a-go/protocol"
)

func TestExtractDACFrame(t *testing.T) {
	name, payload, ok := extractDACFrame("[[DAC_EXECUTION_FLOW]] {\"execution_id\":\"own-1\"}")
	if !ok {
		t.Fatal("expected EF frame to parse")
	}
	if name != "DAC_EXECUTION_FLOW" {
		t.Errorf("name=%q, want DAC_EXECUTION_FLOW", name)
	}
	if payload != "{\"execution_id\":\"own-1\"}" {
		t.Errorf("payload=%q", payload)
	}
}

func TestHandleFramePayload_ExecutionFlowSetsEventType(t *testing.T) {
	c := &client{logger: slog.Default()}
	outputCh := make(chan entity.StreamChunk, 2)
	state := &answerFrameState{}

	c.handleFramePayload("DAC_EXECUTION_FLOW", `{"schema_version":"v1","execution_id":"own-1"}`, outputCh, state)
	close(outputCh)

	chunk := <-outputCh
	if chunk.EventType != "execution-flow" {
		t.Fatalf("expected EventType execution-flow, got %q", chunk.EventType)
	}
	if chunk.Progress != `{"schema_version":"v1","execution_id":"own-1"}` {
		t.Fatalf("unexpected Progress=%q", chunk.Progress)
	}
}

func TestHandleArtifactUpdate_EmitsExecutionFlowEventType(t *testing.T) {
	c := &client{logger: slog.Default()}
	outputCh := make(chan entity.StreamChunk, 4)
	var lineBuf lineBuffer
	var answerState answerFrameState

	tp := protocol.NewTextPart("[[DAC_EXECUTION_FLOW]] {\"schema_version\":\"v1\",\"execution_id\":\"own-1-user-agent-t1\"}\n")
	event := &protocol.TaskArtifactUpdateEvent{
		Artifact: protocol.Artifact{
			Parts: []protocol.Part{&tp},
		},
	}
	c.handleArtifactUpdate(event, outputCh, &lineBuf, &answerState)

	chunk := <-outputCh
	if chunk.EventType != "execution-flow" {
		t.Fatalf("expected EventType execution-flow, got %q", chunk.EventType)
	}
	if !strings.Contains(chunk.Progress, "own-1-user-agent-t1") {
		t.Fatalf("expected execution_id in Progress, got %q", chunk.Progress)
	}
}

func TestExtractDACFramePayload(t *testing.T) {
	tests := []struct {
		line   string
		want   string
		wantOk bool
	}{
		{"[[DAC_PROGRESS]] {\"event\":\"x\"}", "{\"event\":\"x\"}", true},
		{"[[DAC_ANSWER]] {\"event\":\"final_answer\"}", "{\"event\":\"final_answer\"}", true},
		{"[[DAC_OTHER]] {\"event\":\"custom\"}", "{\"event\":\"custom\"}", true},
		{"hello", "", false},
		{"[[DAC_", "", false},
	}
	for _, tt := range tests {
		got, ok := extractDACFramePayload(tt.line)
		if ok != tt.wantOk || got != tt.want {
			t.Errorf("extractDACFramePayload(%q) = %q, %v; want %q, %v", tt.line, got, ok, tt.want, tt.wantOk)
		}
	}
}

func TestLineBuffer_Feed_ProgressOnly(t *testing.T) {
	var b lineBuffer
	frames, content := b.feed("[[DAC_PROGRESS]] {\"event\":\"routing_plan_ready\"}\n")
	if len(frames) != 1 || frames[0].payload != "{\"event\":\"routing_plan_ready\"}" || frames[0].name != "DAC_PROGRESS" {
		t.Errorf("expected one progress payload, got frames=%v", frames)
	}
	if len(content) != 0 {
		t.Errorf("expected no content, got %v", content)
	}
	if b.buf != "" {
		t.Errorf("expected empty buf, got %q", b.buf)
	}
}

func TestLineBuffer_Feed_ContentOnly(t *testing.T) {
	var b lineBuffer
	frames, content := b.feed("hello\nworld\n")
	if len(frames) != 0 {
		t.Errorf("expected no progress, got %v", frames)
	}
	if len(content) != 2 || content[0] != "hello" || content[1] != "world" {
		t.Errorf("expected [hello world], got %v", content)
	}
	if b.buf != "" {
		t.Errorf("expected empty buf, got %q", b.buf)
	}
}

func TestLineBuffer_Feed_Mixed(t *testing.T) {
	var b lineBuffer
	frames, content := b.feed("[[DAC_PROGRESS]] {\"layer\":\"routing\"}\nline1\n")
	if len(frames) != 1 || !strings.Contains(frames[0].payload, "routing") {
		t.Errorf("expected one progress, got %v", frames)
	}
	if len(content) != 1 || content[0] != "line1" {
		t.Errorf("expected [line1], got %v", content)
	}

	frames2, content2 := b.feed("line2\n")
	if len(frames2) != 0 {
		t.Errorf("expected no progress, got %v", frames2)
	}
	if len(content2) != 1 || content2[0] != "line2" {
		t.Errorf("expected [line2], got %v", content2)
	}
}

func TestLineBuffer_Feed_IncompleteLine(t *testing.T) {
	var b lineBuffer
	frames, content := b.feed("[[DAC_PROG")
	if len(frames) != 0 || len(content) != 0 {
		t.Errorf("expected no complete lines, got frames=%v content=%v", frames, content)
	}
	if b.buf != "[[DAC_PROG" {
		t.Errorf("expected buf [[DAC_PROG, got %q", b.buf)
	}

	frames2, content2 := b.feed("RESS]] {\"x\":1}\n")
	if len(frames2) != 1 || frames2[0].payload != "{\"x\":1}" {
		t.Errorf("expected one progress after completion, got %v", frames2)
	}
	if len(content2) != 0 {
		t.Errorf("expected no content, got %v", content2)
	}
	if b.buf != "" {
		t.Errorf("expected empty buf after full line, got %q", b.buf)
	}
}

func TestLineBuffer_Flush(t *testing.T) {
	var b lineBuffer
	_, _ = b.feed("incomplete")
	rem := b.flush()
	if rem != "incomplete" {
		t.Errorf("expected flush to return incomplete, got %q", rem)
	}
	if b.buf != "" {
		t.Errorf("expected buf empty after flush, got %q", b.buf)
	}
}

func TestLineBuffer_ProgressNotInContent(t *testing.T) {
	var b lineBuffer
	_, content := b.feed("[[DAC_PROGRESS]] {\"event\":\"e\"}\nhello\n")
	for _, line := range content {
		if strings.HasPrefix(strings.TrimSpace(line), dacFramePrefix) {
			t.Errorf("DAC frame must not appear in content: %q", line)
		}
	}
}

func TestLineBuffer_Feed_AnswerFrame(t *testing.T) {
	var b lineBuffer
	frames, content := b.feed("[[DAC_ANSWER]] {\"event\":\"final_answer\",\"payload\":{\"text\":\"ok\"}}\n")
	if len(frames) != 1 || frames[0].name != "DAC_ANSWER" || !strings.Contains(frames[0].payload, "final_answer") {
		t.Errorf("expected one frame payload (DAC_ANSWER), got frames=%v", frames)
	}
	if len(content) != 0 {
		t.Errorf("expected no content, got %v", content)
	}
}

func TestLineBuffer_Feed_ProgressAndAnswerNotInContent(t *testing.T) {
	var b lineBuffer
	frames, content := b.feed("[[DAC_PROGRESS]] {\"event\":\"e\"}\n[[DAC_ANSWER]] {\"event\":\"final_answer\"}\nreply\n")
	if len(frames) != 2 {
		t.Errorf("expected 2 frames, got %d", len(frames))
	}
	if len(content) != 1 || content[0] != "reply" {
		t.Errorf("expected [reply], got %v", content)
	}
	for _, line := range content {
		if strings.HasPrefix(strings.TrimSpace(line), dacFramePrefix) {
			t.Errorf("DAC frame must not appear in content: %q", line)
		}
	}
}

func TestParseAnswerFramePayload(t *testing.T) {
	eventName, text, ok := parseAnswerFramePayload(`{"event":"final_answer_chunk","payload":{"text":"hello"}}`)
	if !ok {
		t.Fatal("expected answer frame to parse")
	}
	if eventName != "final_answer_chunk" {
		t.Fatalf("expected event final_answer_chunk, got %q", eventName)
	}
	if text != "hello" {
		t.Fatalf("expected text hello, got %q", text)
	}
}

func TestHandleFramePayload_StreamsFinalAnswerChunksAndSkipsDuplicateFinal(t *testing.T) {
	c := &client{logger: slog.Default()}
	outputCh := make(chan entity.StreamChunk, 4)
	state := &answerFrameState{}

	c.handleFramePayload("DAC_ANSWER", `{"event":"final_answer_chunk","payload":{"text":"hel"}}`, outputCh, state)
	c.handleFramePayload("DAC_ANSWER", `{"event":"final_answer_chunk","payload":{"text":"lo"}}`, outputCh, state)
	c.handleFramePayload("DAC_ANSWER", `{"event":"final_answer","payload":{"text":"hello"}}`, outputCh, state)

	close(outputCh)

	var chunks []entity.StreamChunk
	for chunk := range outputCh {
		chunks = append(chunks, chunk)
	}

	if len(chunks) != 2 {
		t.Fatalf("expected 2 streamed content chunks, got %d", len(chunks))
	}
	if chunks[0].Content != "hel" || chunks[1].Content != "lo" {
		t.Fatalf("unexpected content chunks: %+v", chunks)
	}
}

func TestHandleFramePayload_UsesFinalAnswerAsFallback(t *testing.T) {
	c := &client{logger: slog.Default()}
	outputCh := make(chan entity.StreamChunk, 2)
	state := &answerFrameState{}

	c.handleFramePayload("DAC_ANSWER", `{"event":"final_answer","payload":{"text":"final text"}}`, outputCh, state)

	close(outputCh)

	chunk := <-outputCh
	if chunk.Content != "final text" {
		t.Fatalf("expected fallback final content, got %+v", chunk)
	}
}

// TestHandleArtifactUpdate_EmitsProgressAndContent is a table-driven style test:
// feed a mock TaskArtifactUpdateEvent and assert the sequence of StreamChunk (Progress, Text, IsEnd).
func TestHandleArtifactUpdate_EmitsProgressAndContent(t *testing.T) {
	c := &client{logger: slog.Default()}
	outputCh := make(chan entity.StreamChunk, 10)
	var lineBuf lineBuffer
	var answerState answerFrameState

	tp := protocol.NewTextPart("[[DAC_PROGRESS]] {\"event\":\"routing_plan_ready\"}\ncontent line\n")
	event := &protocol.TaskArtifactUpdateEvent{
		Artifact: protocol.Artifact{
			Parts: []protocol.Part{&tp},
		},
	}
	c.handleArtifactUpdate(event, outputCh, &lineBuf, &answerState)

	var chunks []entity.StreamChunk
	chunks = append(chunks, <-outputCh)
	chunks = append(chunks, <-outputCh)

	if len(chunks) != 2 {
		t.Fatalf("expected 2 chunks, got %d", len(chunks))
	}
	if chunks[0].Progress != "{\"event\":\"routing_plan_ready\"}" {
		t.Errorf("chunk 0: expected progress payload, got Progress=%q", chunks[0].Progress)
	}
	if chunks[1].Text != "content line\n" {
		t.Errorf("chunk 1: expected content line, got Text=%q", chunks[1].Text)
	}
}

func TestHandleArtifactUpdate_ConvertsAnswerFramesToContent(t *testing.T) {
	c := &client{logger: slog.Default()}
	outputCh := make(chan entity.StreamChunk, 10)
	var lineBuf lineBuffer
	var answerState answerFrameState

	tp := protocol.NewTextPart(
		"[[DAC_ANSWER]] {\"event\":\"final_answer_chunk\",\"payload\":{\"text\":\"hel\"}}\n" +
			"[[DAC_ANSWER]] {\"event\":\"final_answer_chunk\",\"payload\":{\"text\":\"lo\"}}\n" +
			"[[DAC_ANSWER]] {\"event\":\"final_answer\",\"payload\":{\"text\":\"hello\"}}\n",
	)
	event := &protocol.TaskArtifactUpdateEvent{
		Artifact: protocol.Artifact{
			Parts: []protocol.Part{&tp},
		},
	}

	c.handleArtifactUpdate(event, outputCh, &lineBuf, &answerState)

	first := <-outputCh
	second := <-outputCh

	if first.Content != "hel" || second.Content != "lo" {
		t.Fatalf("expected answer chunk content, got first=%+v second=%+v", first, second)
	}
	select {
	case extra := <-outputCh:
		t.Fatalf("did not expect duplicate final answer chunk, got %+v", extra)
	default:
	}
}
