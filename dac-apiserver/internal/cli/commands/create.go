package commands

import (
	"context"
	"fmt"
	"time"

	"github.com/AlecAivazis/survey/v2"
	"github.com/spf13/cobra"

	"github.com/lvyanru/dac-apiserver/internal/cli/client"
	"github.com/lvyanru/dac-apiserver/internal/cli/config"
	"github.com/lvyanru/dac-apiserver/internal/cli/loader"
	"github.com/lvyanru/dac-apiserver/internal/cli/ui"
)

var (
	createNamespace string
	createFile      string
)

// createCmd is the parent create command
var createCmd = &cobra.Command{
	Use:   "create",
	Short: "Create resources (DataAgentContainer or DataDescriptor)",
	Long: `Create Kubernetes custom resources for the DAC platform.

Available resource types:
  • dd, datadescriptor      - Create a DataDescriptor (data source configuration)
  • dac, dataagentcontainer - Create a DataAgentContainer (AI agent)

Use subcommands for specific resource types, or use -f to create from a YAML file.`,
	Example: `  # Interactive creation
  $ dactl create dd
  $ dactl create dac

  # Non-interactive creation with flags
  $ dactl create dd --name my-db --type mysql --host localhost
  $ dactl create dac --name my-agent --data-sources my-db

  # Create from YAML file
  $ dactl create -f resource.yaml`,
	RunE: runCreateFromFile, // Only runs when -f is specified
}

func init() {
	// Common flags
	createCmd.PersistentFlags().StringVarP(&createNamespace, "namespace", "n", "default", "Kubernetes namespace")
	createCmd.Flags().StringVarP(&createFile, "file", "f", "", "YAML file containing resource definition")

	// Add subcommands
	createCmd.AddCommand(createDDCmd)
	createCmd.AddCommand(createDACCmd)

	// Silence usage to avoid showing help on every error
	createCmd.SilenceUsage = true
}

// runCreateFromFile handles creation from YAML file
func runCreateFromFile(cmd *cobra.Command, args []string) error {
	// If no file specified and no subcommand, show help
	if createFile == "" {
		return cmd.Help()
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
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

	return createFromFile(ctx, apiClient, createFile, createNamespace)
}

// createFromFile creates a resource from a YAML file
func createFromFile(ctx context.Context, apiClient *client.APIClient, filepath, namespaceOverride string) error {
	ui.PrintInfo("Loading resource from file: %s", filepath)

	// Load YAML file
	resource, err := loader.LoadFromFile(filepath)
	if err != nil {
		ui.PrintError("failed to load file: %v", err)
		return fmt.Errorf("file load failed")
	}

	ui.PrintSuccess("File loaded successfully")
	ui.PrintInfo("Resource Kind: %s", resource.Kind)
	fmt.Println()

	// Create resource based on kind
	switch resource.Kind {
	case "DataAgentContainer":
		return createDACFromResource(ctx, apiClient, resource, namespaceOverride)
	case "DataDescriptor":
		return createDDFromResource(ctx, apiClient, resource, namespaceOverride)
	default:
		ui.PrintError("invalid resource kind: %s", resource.Kind)
		return fmt.Errorf("invalid resource kind")
	}
}

// createDACFromResource creates a DataAgentContainer from ResourceFile
func createDACFromResource(ctx context.Context, apiClient *client.APIClient, resource *loader.ResourceFile, namespaceOverride string) error {
	// Convert to CreateDACRequest
	req, err := resource.ToCreateDACRequest()
	if err != nil {
		ui.PrintError("invalid resource specification: %v", err)
		return fmt.Errorf("validation failed")
	}

	// Override namespace if specified via command line
	if namespaceOverride != "" && namespaceOverride != "default" {
		req.Namespace = namespaceOverride
	}

	// Display configuration
	ui.PrintInfo("Creating DataAgentContainer:")
	fmt.Printf("  Name: %s\n", req.Name)
	fmt.Printf("  Namespace: %s\n", req.Namespace)
	fmt.Printf("  Description: %s\n", req.AgentCard.Description)
	fmt.Printf("  Data Sources: %v\n", req.DataPolicy.SourceNameSelector)
	fmt.Printf("  Model: %s / %s\n", req.Model.ExpertLLM, req.Model.Embedding)
	fmt.Printf("  Max Steps: %s\n", req.ExpertAgentMaxSteps)
	if len(req.Labels) > 0 {
		fmt.Printf("  Labels: %v\n", req.Labels)
	}
	fmt.Println()

	// Confirm creation
	confirm := false
	confirmPrompt := &survey.Confirm{
		Message: "Confirm creation?",
		Default: true,
	}
	if err := survey.AskOne(confirmPrompt, &confirm); err != nil {
		return fmt.Errorf("confirmation cancelled")
	}

	if !confirm {
		ui.PrintInfo("Cancelled")
		return nil
	}

	// Create resource
	ui.PrintInfo("Creating...")
	if err := apiClient.CreateAgentContainer(ctx, req); err != nil {
		ui.PrintError("Failed to create: %v", err)
		return fmt.Errorf("creation failed")
	}

	ui.PrintSuccess("DataAgentContainer '%s' created successfully!", req.Name)
	fmt.Println()
	fmt.Printf("View resource: dactl list -n %s\n", req.Namespace)

	return nil
}

// createDDFromResource creates a DataDescriptor from ResourceFile
func createDDFromResource(ctx context.Context, apiClient *client.APIClient, resource *loader.ResourceFile, namespaceOverride string) error {
	// Convert to CreateDDRequest
	req, err := resource.ToCreateDDRequest()
	if err != nil {
		ui.PrintError("invalid resource specification: %v", err)
		return fmt.Errorf("validation failed")
	}

	// Override namespace if specified via command line
	if namespaceOverride != "" && namespaceOverride != "default" {
		req.Namespace = namespaceOverride
	}

	// Display configuration
	ui.PrintInfo("Creating DataDescriptor:")
	fmt.Printf("  Name: %s\n", req.Name)
	fmt.Printf("  Namespace: %s\n", req.Namespace)
	fmt.Printf("  Type: %s\n", req.DescriptorType)
	fmt.Printf("  Sources: %d data source(s)\n", len(req.Sources))
	if len(req.Labels) > 0 {
		fmt.Printf("  Labels: %v\n", req.Labels)
	}
	for i, src := range req.Sources {
		fmt.Printf("  Source %d:\n", i+1)
		fmt.Printf("    Name: %s\n", src.Name)
		fmt.Printf("    Type: %s\n", src.Type)
		if host, ok := src.Metadata["host"]; ok {
			port := src.Metadata["port"]
			fmt.Printf("    Connection: %s:%s\n", host, port)
		}
		if src.Extract != nil && len(src.Extract.Tables) > 0 {
			fmt.Printf("    Tables: %v\n", src.Extract.Tables)
		}
	}
	fmt.Println()

	// Confirm creation
	confirm := false
	confirmPrompt := &survey.Confirm{
		Message: "Confirm creation?",
		Default: true,
	}
	if err := survey.AskOne(confirmPrompt, &confirm); err != nil {
		return fmt.Errorf("confirmation cancelled")
	}

	if !confirm {
		ui.PrintInfo("Cancelled")
		return nil
	}

	// Create resource
	ui.PrintInfo("Creating...")
	if err := apiClient.CreateDataDescriptor(ctx, req); err != nil {
		ui.PrintError("Failed to create: %v", err)
		return fmt.Errorf("creation failed")
	}

	ui.PrintSuccess("DataDescriptor '%s' created successfully!", req.Name)
	fmt.Println()
	fmt.Printf("View resource: dactl list -n %s\n", req.Namespace)

	return nil
}

// getDefaultPort returns the default port for a given database type
func getDefaultPort(dbType string) string {
	switch dbType {
	case "mysql":
		return "3306"
	case "postgres":
		return "5432"
	case "minio":
		return "9000"
	case "fileserver":
		return "8080"
	default:
		return "3306"
	}
}
