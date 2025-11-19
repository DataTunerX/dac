package commands

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/lvyanru/dac-apiserver/internal/cli/ui"
)

const version = "0.1.0"

// rootCmd is the root command
var rootCmd = &cobra.Command{
	Use:     "dactl",
	Short:   "Data Agent Container CLI",
	Version: version,
	Long: `A command-line tool for managing DataAgentContainers (DAC) and DataDescriptors (DD)
in your Kubernetes cluster. Provides interactive chat, resource management, and
observability for your data agents.`,
	Example: `  # Authenticate with API server
  $ dactl login -s http://localhost:8080 -u admin

  # List all resources in default namespace
  $ dactl list

  # List resources across all namespaces
  $ dactl list -A

  # Start interactive chat
  $ dactl chat

  # Get help on a specific command
  $ dactl list --help`,
}

// Execute executes the root command
func Execute() error {
	rootCmd.SetVersionTemplate(formatVersion())
	return rootCmd.Execute()
}

func init() {
	// Disable default completion command
	rootCmd.CompletionOptions.DisableDefaultCmd = true

	// Add subcommands
	rootCmd.AddCommand(loginCmd)
	rootCmd.AddCommand(listCmd)
	rootCmd.AddCommand(createCmd)
	rootCmd.AddCommand(deleteCmd)
	rootCmd.AddCommand(chatCmd)

	// Set custom template with bold uppercase headers
	rootCmd.SetUsageTemplate(usageTemplate())
	rootCmd.SetHelpTemplate(usageTemplate())
}

func usageTemplate() string {
	return `{{if .Long}}{{.Long}}

{{end}}` + ui.Styles.Bold.Render("USAGE") + `
  {{.UseLine}}{{if .HasAvailableSubCommands}}
  {{.CommandPath}} [command]{{end}}

{{if .HasExample}}` + ui.Styles.Bold.Render("EXAMPLES") + `
{{.Example}}

{{end}}{{if .HasAvailableSubCommands}}` + ui.Styles.Bold.Render("COMMANDS") + `{{range .Commands}}{{if (or .IsAvailableCommand (eq .Name "help"))}}
  {{rpad .Name .NamePadding }} {{.Short}}{{end}}{{end}}

{{end}}{{if .HasAvailableLocalFlags}}` + ui.Styles.Bold.Render("OPTIONS") + `
{{.LocalFlags.FlagUsages | trimTrailingWhitespaces}}

{{end}}{{if .HasAvailableSubCommands}}Use "{{.CommandPath}} [command] --help" for more information about a command.{{end}}
`
}

// formatVersion formats the version output
func formatVersion() string {
	return fmt.Sprintf("dactl version %s\n", version)
}
