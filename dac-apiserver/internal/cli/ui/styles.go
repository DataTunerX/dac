package ui

import "github.com/charmbracelet/lipgloss"

// Styles defines all lipgloss styles used in the CLI
var Styles = struct {
	Bold       lipgloss.Style
	SuccessBox lipgloss.Style
	ErrorBox   lipgloss.Style
}{
	Bold: lipgloss.NewStyle().Bold(true),

	SuccessBox: lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("42")).
		Padding(0, 1).
		Width(60),

	ErrorBox: lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("196")).
		Padding(0, 1).
		Width(60),
}
