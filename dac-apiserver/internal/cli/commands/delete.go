package commands

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/AlecAivazis/survey/v2"
	"github.com/spf13/cobra"

	"github.com/lvyanru/dac-apiserver/internal/cli/client"
	"github.com/lvyanru/dac-apiserver/internal/cli/config"
	"github.com/lvyanru/dac-apiserver/internal/cli/ui"
)

var (
	deleteNamespace string
	deleteForce     bool
)

// deleteCmd is the delete command
var deleteCmd = &cobra.Command{
	Use:   "delete <resource-type> <name>",
	Short: "delete a DataAgentContainer or DataDescriptor",
	Long: `Delete a DataAgentContainer or DataDescriptor.

Resource Types:
  • dac, dataagentcontainer       - DataAgentContainer
  • dd, datadescriptor            - DataDescriptor

By default, you will be prompted to confirm the deletion. Use --force to skip confirmation.`,
	Example: `  # Delete a DataAgentContainer
  $ dactl delete dac my-agent
  $ dactl delete dataagentcontainer my-agent -n production

  # Delete a DataDescriptor
  $ dactl delete dd my-database
  $ dactl delete datadescriptor my-database -n dev

  # Force delete without confirmation
  $ dactl delete dac my-agent --force`,
	Args: cobra.ExactArgs(2), // Require exactly 2 arguments: resource-type and name
	RunE: runDelete,
}

func init() {
	deleteCmd.Flags().StringVarP(&deleteNamespace, "namespace", "n", "default", "Kubernetes namespace")
	deleteCmd.Flags().BoolVarP(&deleteForce, "force", "f", false, "Skip confirmation prompt")

	// Silence usage to avoid showing help on every error
	deleteCmd.SilenceUsage = true
}

func runDelete(cmd *cobra.Command, args []string) error {
	// Args are already validated by cobra.ExactArgs(2)
	resourceType := strings.ToLower(args[0])
	resourceName := args[1]

	// Validate resource type
	var isDAC bool
	switch resourceType {
	case "dac", "dataagentcontainer":
		isDAC = true
	case "dd", "datadescriptor":
		isDAC = false
	default:
		ui.PrintError("invalid resource type: %s", resourceType)
		fmt.Println("\nValid types:")
		fmt.Println("  • dac, dataagentcontainer")
		fmt.Println("  • dd, datadescriptor")
		fmt.Printf("\nRun '%s --help' for usage.\n", cmd.CommandPath())
		return fmt.Errorf("invalid resource type")
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

	// Confirm deletion unless --force
	if !deleteForce {
		var resourceTypeDisplay string
		if isDAC {
			resourceTypeDisplay = "DataAgentContainer"
		} else {
			resourceTypeDisplay = "DataDescriptor"
		}

		confirm := false
		prompt := &survey.Confirm{
			Message: fmt.Sprintf("Delete %s '%s' in namespace '%s'?",
				resourceTypeDisplay, resourceName, deleteNamespace),
		}
		if err := survey.AskOne(prompt, &confirm); err != nil {
			return fmt.Errorf("confirmation prompt failed: %w", err)
		}

		if !confirm {
			ui.PrintInfo("Deletion cancelled")
			return nil
		}
	}

	// Perform deletion
	ui.PrintInfo("Deleting %s '%s' in namespace '%s'...", resourceType, resourceName, deleteNamespace)

	if isDAC {
		err = apiClient.DeleteAgentContainer(ctx, deleteNamespace, resourceName)
	} else {
		err = apiClient.DeleteDataDescriptor(ctx, deleteNamespace, resourceName)
	}

	if err != nil {
		ui.PrintError("failed to delete: %v", err)
		return fmt.Errorf("deletion failed")
	}

	ui.PrintSuccess("Successfully deleted %s '%s'", resourceType, resourceName)
	return nil
}
