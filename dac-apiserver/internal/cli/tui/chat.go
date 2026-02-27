package tui

import (
	"context"
	"fmt"
	"strings"

	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
	"github.com/mattn/go-runewidth"

	"github.com/lvyanru/dac-apiserver/internal/cli/client"
	"github.com/lvyanru/dac-apiserver/internal/cli/types"
)

// UI configuration constants
const (
	defaultInputWidth      = 100
	defaultViewportWidth   = 100
	defaultViewportHeight  = 30
	defaultWindowWidth     = 100
	defaultWindowHeight    = 40
	inputCharLimit         = 4000
	inputHeightReserved    = 2
	statusHeightReserved   = 3
	minContentHeight       = 10
	sessionIDDisplayLength = 8
)

// Style definitions - Claude Code style
var (
	dimStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("240"))
	boldStyle   = lipgloss.NewStyle().Bold(true)
	accentStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("86"))
	errorStyle  = lipgloss.NewStyle().Foreground(lipgloss.Color("196"))
	promptStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("63"))
)

// streamState represents the state of streaming response
type streamState int

const (
	streamIdle streamState = iota
	streamStreaming
)

// ChatProgram encapsulates the chat TUI program
type ChatProgram struct {
	model chatModel
}

// NewChatProgram creates a new chat program instance
func NewChatProgram(apiClient *client.APIClient, runID string) *ChatProgram {
	return &ChatProgram{model: initialModel(apiClient, runID)}
}

// Run starts the chat TUI program
func (p *ChatProgram) Run() error {
	program := tea.NewProgram(p.model, tea.WithAltScreen())
	_, err := program.Run()
	return err
}

// chatModel is the Bubble Tea model containing all chat interface state
type chatModel struct {
	// Dependencies
	apiClient *client.APIClient
	runID     string

	// UI components
	input       textinput.Model
	contentView viewport.Model

	// Streaming response state
	state      streamState
	content    *strings.Builder // Use pointer to avoid Builder copy
	streamLine string
	lineBuffer string

	// Content filtering state
	inAnswer   bool // Flag indicating if answer line has been encountered
	tasksShown bool // Flag indicating if task list has been shown

	// Streaming data channels
	chunkCh <-chan types.ChatStreamChunk
	errCh   <-chan error

	// Error state
	err error

	// Window dimensions
	width  int
	height int
}

// initialModel creates the initial chat model
func initialModel(apiClient *client.APIClient, runID string) chatModel {
	input := textinput.New()
	input.Placeholder = ""
	input.Focus()
	input.CharLimit = inputCharLimit
	input.Width = defaultInputWidth
	input.Prompt = ""
	input.TextStyle = lipgloss.NewStyle()
	input.PromptStyle = lipgloss.NewStyle()

	contentViewport := viewport.New(defaultViewportWidth, defaultViewportHeight)
	contentViewport.SetContent("")

	return chatModel{
		apiClient:   apiClient,
		runID:       runID,
		input:       input,
		contentView: contentViewport,
		state:       streamIdle,
		content:     &strings.Builder{},
		width:       defaultWindowWidth,
		height:      defaultWindowHeight,
	}
}

// Init initializes the model (Bubble Tea interface)
func (m chatModel) Init() tea.Cmd {
	return textinput.Blink
}

// Message type definitions
type (
	streamInitMsg struct {
		chunkCh <-chan types.ChatStreamChunk
		errCh   <-chan error
	}
	streamChunkMsg struct{ chunk types.ChatStreamChunk }
	streamErrMsg   struct{ err error }
	streamDoneMsg  struct{}
)

// Update processes messages and updates the model (Bubble Tea interface)
func (m chatModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {
	case tea.KeyMsg:
		cmds = append(cmds, m.handleKeyPress(msg)...)

	case tea.WindowSizeMsg:
		m.handleWindowResize(msg)

	case streamInitMsg:
		m.state = streamStreaming
		m.chunkCh = msg.chunkCh
		m.errCh = msg.errCh
		cmds = append(cmds, waitForChunk(m.chunkCh, m.errCh))

	case streamChunkMsg:
		m.handleChunk(msg.chunk)
		cmds = append(cmds, waitForChunk(m.chunkCh, m.errCh))

	case streamErrMsg:
		m.err = msg.err
		m.state = streamIdle
		m.chunkCh, m.errCh = nil, nil
		m.refreshContent()

	case streamDoneMsg:
		m.finishStream()
	}

	// 非流式状态下更new输入框
	if m.state != streamStreaming {
		var cmd tea.Cmd
		m.input, cmd = m.input.Update(msg)
		cmds = append(cmds, cmd)
	}

	return m, tea.Batch(cmds...)
}

// handleKeyPress handles keyboard input
func (m *chatModel) handleKeyPress(msg tea.KeyMsg) []tea.Cmd {
	var cmds []tea.Cmd

	switch msg.Type {
	case tea.KeyCtrlC, tea.KeyEsc:
		cmds = append(cmds, tea.Quit)

	case tea.KeyEnter:
		if m.state != streamStreaming {
			text := strings.TrimSpace(m.input.Value())
			if text != "" {
				m.startStreaming(text)
				cmds = append(cmds, m.initStream(text))
			}
		}

	case tea.KeyUp:
		m.contentView.LineUp(1)

	case tea.KeyDown:
		m.contentView.LineDown(1)

	case tea.KeyPgUp:
		m.contentView.ViewUp()

	case tea.KeyPgDown:
		m.contentView.ViewDown()
	}

	return cmds
}

// handleWindowResize handles window size changes
func (m *chatModel) handleWindowResize(msg tea.WindowSizeMsg) {
	m.width = msg.Width
	m.height = msg.Height

	contentHeight := msg.Height - inputHeightReserved - statusHeightReserved
	if contentHeight < minContentHeight {
		contentHeight = minContentHeight
	}

	m.contentView.Width = msg.Width
	m.contentView.Height = contentHeight
	m.input.Width = msg.Width - 3

	// Reapply wrapping when window size changes
	m.refreshContent()
}

// startStreaming starts a new streaming conversation
func (m *chatModel) startStreaming(text string) {
	m.input.Reset()
	// reset streaming state
	m.streamLine = ""
	m.lineBuffer = ""
	m.inAnswer = false
	m.tasksShown = false

	// append user message to content
	m.content.WriteString("\n")
	m.content.WriteString(boldStyle.Render("You"))
	m.content.WriteString("\n")
	m.content.WriteString(text)
	m.content.WriteString("\n\n")
	m.content.WriteString(accentStyle.Render("Assistant"))
	m.content.WriteString("\n")

	m.state = streamStreaming
	m.refreshContent()
}

// finishStream completes the streaming response
func (m *chatModel) finishStream() {
	m.state = streamIdle
	m.chunkCh, m.errCh = nil, nil
	m.streamLine = ""
	m.lineBuffer = ""

	m.refreshContent()
}

// initStream initializes a streaming request
func (m *chatModel) initStream(prompt string) tea.Cmd {
	return func() tea.Msg {
		ctx := context.Background()
		messages := []types.ChatMessage{{Role: "user", Content: prompt}}
		chunkCh, errCh, err := m.apiClient.ChatStreaming(ctx, messages, m.runID)
		if err != nil {
			return streamErrMsg{err: err}
		}
		return streamInitMsg{chunkCh: chunkCh, errCh: errCh}
	}
}

// waitForChunk waits for the next streaming data chunk
func waitForChunk(chunkCh <-chan types.ChatStreamChunk, errCh <-chan error) tea.Cmd {
	return func() tea.Msg {
		select {
		case chunk, ok := <-chunkCh:
			if !ok {
				return streamDoneMsg{}
			}
			return streamChunkMsg{chunk: chunk}
		case err, ok := <-errCh:
			if !ok {
				return streamDoneMsg{}
			}
			if err != nil {
				return streamErrMsg{err: err}
			}
			return streamDoneMsg{}
		}
	}
}

// handleChunk processes received streaming data chunks
func (m *chatModel) handleChunk(chunk types.ChatStreamChunk) {
	if len(chunk.Choices) == 0 {
		return
	}
	delta := chunk.Choices[0].Delta.Content
	if delta == "" {
		return
	}

	// Simply append streamed content as-is
	m.content.WriteString(delta)
	m.streamLine = ""

	m.refreshContent()
}

// refreshContent refreshes the display content
func (m *chatModel) refreshContent() {
	display := m.content.String()
	if m.streamLine != "" {
		display += m.streamLine
	}
	if m.err != nil {
		display += "\n" + errorStyle.Render(fmt.Sprintf("Error: %v", m.err))
	}

	// Auto-wrap handling
	if m.width > 0 {
		display = m.wrapText(display, m.width)
	}

	m.contentView.SetContent(display)
	m.contentView.GotoBottom()
}

// wrapText applies auto-wrapping to text, correctly handling Chinese character widths
func (m *chatModel) wrapText(text string, maxWidth int) string {
	if maxWidth <= 10 {
		return text
	}

	lines := strings.Split(text, "\n")
	var result strings.Builder

	for i, line := range lines {
		if i > 0 {
			result.WriteString("\n")
		}

		// Keep empty lines as-is
		if strings.TrimSpace(line) == "" {
			continue
		}

		// Wrap each line
		wrappedLine := m.wrapLine(line, maxWidth)
		result.WriteString(wrappedLine)
	}

	return result.String()
}

// wrapLine wraps a single line of text, correctly handling Chinese character widths
func (m *chatModel) wrapLine(line string, maxWidth int) string {
	if runewidth.StringWidth(line) <= maxWidth {
		return line
	}

	var result strings.Builder
	var currentLine strings.Builder
	currentWidth := 0

	for _, r := range line {
		runeW := runewidth.RuneWidth(r)

		// If adding this character exceeds width, wrap first
		if currentWidth+runeW > maxWidth && currentWidth > 0 {
			result.WriteString(currentLine.String())
			result.WriteString("\n")
			currentLine.Reset()
			currentWidth = 0
		}

		currentLine.WriteRune(r)
		currentWidth += runeW
	}

	// Add final line
	if currentLine.Len() > 0 {
		result.WriteString(currentLine.String())
	}

	return result.String()
}

// View renders the UI (Bubble Tea interface)
func (m chatModel) View() string {
	// Top status bar
	status := dimStyle.Render(fmt.Sprintf("Session %s", m.runID[:sessionIDDisplayLength]))
	if m.state == streamStreaming {
		status += dimStyle.Render(" • generating...")
	}

	// Content area
	content := m.contentView.View()

	// Input area
	var inputView string
	if m.state == streamStreaming {
		inputView = dimStyle.Render("> ") + dimStyle.Render("Waiting for response...")
	} else {
		inputView = promptStyle.Render("> ") + m.input.View()
	}

	// Bottom help text
	help := ""
	if m.state != streamStreaming {
		help = dimStyle.Render("Enter to send • ↑↓ scroll • Esc to exit")
	}

	parts := []string{status, "", content, "", inputView}
	if help != "" {
		parts = append(parts, help)
	}

	return lipgloss.JoinVertical(lipgloss.Left, parts...)
}
