package commands

import (
	"context"
	"fmt"
	"time"

	"github.com/spf13/cobra"

	"github.com/lvyanru/dac-apiserver/internal/cli/client"
	"github.com/lvyanru/dac-apiserver/internal/cli/config"
	"github.com/lvyanru/dac-apiserver/internal/cli/ui"
)

var (
	listNamespace     string
	listAllNamespaces bool
)

// listCmd is the list command
var listCmd = &cobra.Command{
	Use:   "list",
	Short: "list DataAgentContainers and DataDescriptors",
	Long: `List DataAgentContainers and DataDescriptors in a tree view.

Displays all DataAgentContainers (DAC) and their associated DataDescriptors (DD)
in a tree structure, showing relationships, status, and connection details.

The output includes:
  • DataAgentContainer names, endpoints, and status
  • Associated DataDescriptors with database connections  
  • Resource phase information (Creating, Ready, Error, etc.)
  • Orphaned DataDescriptors (not referenced by any DAC)`,
	Example: `  # List resources in default namespace
  $ dactl list

  # List resources in specific namespace
  $ dactl list -n production
  $ dactl list --namespace dev

  # List resources across all namespaces
  $ dactl list -A
  $ dactl list --all-namespaces`,
	RunE: runList,
}

func init() {
	listCmd.Flags().StringVarP(&listNamespace, "namespace", "n", "default", "Kubernetes namespace")
	listCmd.Flags().BoolVarP(&listAllNamespaces, "all-namespaces", "A", false, "List resources across all namespaces")

	// Silence usage to avoid showing help on every error
	listCmd.SilenceUsage = true
}

func runList(cmd *cobra.Command, args []string) error {
	// Validate arguments
	if len(args) > 0 {
		ui.PrintError("unexpected argument: %s", args[0])
		fmt.Printf("\nRun '%s --help' for usage.\n", cmd.CommandPath())
		return fmt.Errorf("invalid arguments")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Load config
	cfg, err := config.Load()
	if err != nil {
		ui.PrintError("failed to load config: %v", err)
		return fmt.Errorf("config load failed")
	}

	if !cfg.IsAuthenticated() {
		ui.PrintError("not authenticated, please login first")
		fmt.Println("\nRun 'dactl login' to authenticate.")
		return fmt.Errorf("authentication required")
	}

	// Create API client
	apiClient, err := client.NewAPIClient(cfg.Server, cfg.AccessToken)
	if err != nil {
		ui.PrintError("failed to create client: %v", err)
		return fmt.Errorf("client creation failed")
	}

	// Determine namespace to query
	var queryNamespace string
	var showNamespaceRoot bool

	if listAllNamespaces {
		ui.PrintInfo("Fetching resources from all namespaces...")
		queryNamespace = ""      // Empty namespace means all namespaces
		showNamespaceRoot = true // Show namespace grouping for all-namespaces
	} else {
		ui.PrintInfo("Fetching resources from namespace '%s'...", listNamespace)
		queryNamespace = listNamespace
		showNamespaceRoot = false // Don't show namespace root for single namespace
	}

	// Fetch DataAgentContainers
	agents, err := apiClient.ListAgentContainers(ctx, queryNamespace)
	if err != nil {
		ui.PrintError("failed to list DataAgentContainer: %v", err)
		return fmt.Errorf("list operation failed")
	}

	// Fetch DataDescriptors
	descriptors, err := apiClient.ListDataDescriptors(ctx, queryNamespace)
	if err != nil {
		ui.PrintError("failed to list DataDescriptor: %v", err)
		return fmt.Errorf("list operation failed")
	}

	// Render and display results using UI package
	fmt.Println()

	// When showing all namespaces, group by namespace
	if showNamespaceRoot {
		output := ui.RenderResourceTreeGroupedByNamespace(agents, descriptors)
		fmt.Println(output)
	} else {
		output := ui.RenderResourceTree(agents, descriptors, "", false)
		fmt.Println(output)
	}

	fmt.Println(ui.RenderResourceSummary(len(agents), len(descriptors)))

	return nil
}
