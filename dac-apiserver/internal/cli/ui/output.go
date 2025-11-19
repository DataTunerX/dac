package ui

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
	"github.com/fatih/color"
)

var (
	// Color definitions for terminal output
	successColor = color.New(color.FgGreen, color.Bold)
	errorColor   = color.New(color.FgRed, color.Bold)
	warningColor = color.New(color.FgYellow, color.Bold)
	infoColor    = color.New(color.FgCyan)
	boldColor    = color.New(color.Bold)
)

// PrintSuccess prints a success message
func PrintSuccess(format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	successColor.Printf("✓ %s\n", msg)
}

// PrintError prints an error message
func PrintError(format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	errorColor.Printf("✗ %s\n", msg)
}

// PrintWarning prints a warning message
func PrintWarning(format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	warningColor.Printf("⚠ %s\n", msg)
}

// PrintInfo prints an info message
func PrintInfo(format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	infoColor.Printf("ℹ %s\n", msg)
}

// PrintBold prints a bold message
func PrintBold(format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	boldColor.Println(msg)
}

// PrintBoldNoNewline prints a bold message without newline
func PrintBoldNoNewline(format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	boldColor.Print(msg)
}

// ClearScreen clears the terminal screen
func ClearScreen() {
	fmt.Print("\033[H\033[2J")
}

// PrintChatWelcomeBanner prints the welcome banner for chat mode
func PrintChatWelcomeBanner() {
	// Use lipgloss to create a modern banner
	titleStyle := lipgloss.NewStyle().
		Bold(true).
		Foreground(lipgloss.Color("86")). // Cyan
		Align(lipgloss.Center).
		Width(60).
		MarginTop(1).
		MarginBottom(1)

	bannerStyle := lipgloss.NewStyle().
		Border(lipgloss.RoundedBorder()).
		BorderForeground(lipgloss.Color("86")). // Cyan
		Padding(1, 2).
		Align(lipgloss.Center)

	title := titleStyle.Render("🤖  Data Agent Chat - Interactive Mode")
	banner := bannerStyle.Render(title)

	fmt.Println(banner)
}

// PrintSuccessBox prints a success message in a box
func PrintSuccessBox(title, content string) {
	boxContent := fmt.Sprintf("%s\n\n%s",
		successColor.Sprint(title),
		content,
	)
	fmt.Println(Styles.SuccessBox.Render(boxContent))
}

// PrintErrorBox prints an error message in a box
func PrintErrorBox(title, content string) {
	boxContent := fmt.Sprintf("%s\n\n%s",
		errorColor.Sprint(title),
		content,
	)
	fmt.Println(Styles.ErrorBox.Render(boxContent))
}
