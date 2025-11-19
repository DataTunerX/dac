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
	"github.com/lvyanru/dac-apiserver/internal/cli/types"
	"github.com/lvyanru/dac-apiserver/internal/cli/ui"
)

var (
	// DataAgentContainer flags
	dacName        string
	dacDescription string
	dacDataSources string
	dacModel       string
	dacMaxSteps    string
)

// createDACCmd is the DataAgentContainer create subcommand
var createDACCmd = &cobra.Command{
	Use:     "dac",
	Aliases: []string{"dataagentcontainer"},
	Short:   "Create a DataAgentContainer",
	Long: `Create a DataAgentContainer resource for deploying AI agents.

A DataAgentContainer is an AI agent that can process queries and interact with
data sources configured through DataDescriptors. It uses large language models
to understand requests and generate responses based on your data.

You can create a DataAgentContainer in two ways:
  1. Interactive mode (will prompt for all required fields)
  2. Non-interactive mode using command-line flags`,
	Example: `  # Interactive creation (will prompt for details)
  $ dactl create dac

  # Create with flags (non-interactive)
  $ dactl create dac --name sales-agent \
    --description "AI agent for sales data analysis" \
    --data-sources my-mysql-db,customer-data \
    --model qwen-max \
    --max-steps 5

  # Create with default model (qwen-max)
  $ dactl create dac --name customer-support \
    --data-sources support-db,knowledge-base

  # Create in specific namespace
  $ dactl create dac -n production \
    --name prod-agent \
    --data-sources prod-db \
    --model qwen-plus`,
	RunE: runCreateDAC,
}

func init() {
	// DataAgentContainer-specific flags
	createDACCmd.Flags().StringVar(&dacName, "name", "", "DataAgentContainer name (required for non-interactive mode)")
	createDACCmd.Flags().StringVar(&dacDescription, "description", "", "Agent description (auto-generated if not specified)")
	createDACCmd.Flags().StringVar(&dacDataSources, "data-sources", "", "Comma-separated list of DataDescriptor names")
	createDACCmd.Flags().StringVar(&dacModel, "model", "qwen-max", "LLM model: qwen-max, qwen-plus, qwen-turbo")
	createDACCmd.Flags().StringVar(&dacMaxSteps, "max-steps", "5", "Expert agent maximum iteration steps")
}

func runCreateDAC(cmd *cobra.Command, args []string) error {
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

	// Check if flags are provided for non-interactive mode
	if dacName != "" && dacDataSources != "" {
		return createDataAgentContainerFromFlags(ctx, apiClient, createNamespace)
	}

	// Interactive mode
	return createDataAgentContainerInteractive(ctx, apiClient, createNamespace)
}

// createDataAgentContainerFromFlags creates DataAgentContainer from command-line flags (non-interactive)
func createDataAgentContainerFromFlags(ctx context.Context, apiClient *client.APIClient, namespace string) error {
	// Parse data sources
	ddNames := strings.Split(dacDataSources, ",")
	for i := range ddNames {
		ddNames[i] = strings.TrimSpace(ddNames[i])
	}

	// Set default description if not provided
	if dacDescription == "" {
		dacDescription = fmt.Sprintf("Data Agent for %s", dacName)
	}

	// Build model spec based on model flag
	var modelSpec types.ModelSpec
	switch dacModel {
	case "qwen-max":
		modelSpec.ExpertLLM = "qwen-max"
		modelSpec.PlannerLLM = "qwen-max"
		modelSpec.Embedding = "text-embedding-v3"
	case "qwen-plus":
		modelSpec.ExpertLLM = "qwen-plus"
		modelSpec.PlannerLLM = "qwen-plus"
		modelSpec.Embedding = "text-embedding-v2"
	case "qwen-turbo":
		modelSpec.ExpertLLM = "qwen-turbo"
		modelSpec.PlannerLLM = "qwen-turbo"
		modelSpec.Embedding = "text-embedding-v2"
	default:
		ui.PrintError("invalid model: %s (use qwen-max, qwen-plus, or qwen-turbo)", dacModel)
		return fmt.Errorf("invalid model")
	}

	// Build create request
	req := &types.CreateDACRequest{
		Name:      dacName,
		Namespace: namespace,
		DataPolicy: types.DataPolicy{
			SourceNameSelector: ddNames,
		},
		AgentCard: types.AgentCard{
			Name:        dacName,
			Description: dacDescription,
			Skills:      []types.AgentSkill{},
		},
		Model:               modelSpec,
		ExpertAgentMaxSteps: dacMaxSteps,
	}

	// Display configuration
	ui.PrintInfo("Creating DataAgentContainer:")
	fmt.Printf("  Name: %s\n", dacName)
	fmt.Printf("  Namespace: %s\n", namespace)
	fmt.Printf("  Description: %s\n", dacDescription)
	fmt.Printf("  Data Sources: %v\n", ddNames)
	fmt.Printf("  Model: %s / %s\n", modelSpec.ExpertLLM, modelSpec.Embedding)
	fmt.Printf("  Max Steps: %s\n", dacMaxSteps)
	fmt.Println()

	// Create the resource
	ui.PrintInfo("Creating...")
	if err := apiClient.CreateAgentContainer(ctx, req); err != nil {
		ui.PrintError("Failed to create: %v", err)
		return fmt.Errorf("creation failed")
	}

	ui.PrintSuccess("DataAgentContainer '%s' created successfully!", dacName)
	fmt.Println()
	fmt.Printf("View resource: dactl list -n %s\n", namespace)

	return nil
}

// createDataAgentContainerInteractive guides user through DAC creation (interactive mode)
func createDataAgentContainerInteractive(ctx context.Context, apiClient *client.APIClient, namespace string) error {
	ui.PrintInfo("Creating DataAgentContainer (Interactive Mode)")
	fmt.Println()

	// Step 1: Check for existing DataDescriptors
	ui.PrintInfo("Checking dependencies...")
	descriptors, err := apiClient.ListDataDescriptors(ctx, namespace)
	if err != nil {
		ui.PrintError("failed to check dependencies: %v", err)
		return fmt.Errorf("dependency check failed")
	}

	if len(descriptors) == 0 {
		ui.PrintWarning("No DataDescriptor found in namespace '%s'", namespace)
		fmt.Println()

		// Prompt to create DD first
		createDD := false
		prompt := &survey.Confirm{
			Message: "Create a DataDescriptor first?",
			Default: true,
		}
		if err := survey.AskOne(prompt, &createDD); err != nil {
			return fmt.Errorf("prompt cancelled")
		}

		if createDD {
			// Guide to create DD first
			if err := createDataDescriptorInteractive(ctx, apiClient, namespace); err != nil {
				return err
			}

			// Re-check descriptors
			descriptors, err = apiClient.ListDataDescriptors(ctx, namespace)
			if err != nil || len(descriptors) == 0 {
				ui.PrintError("No DataDescriptor available, cannot continue")
				return fmt.Errorf("no descriptors available")
			}
		} else {
			ui.PrintInfo("Cancelled. Please create a DataDescriptor first.")
			return nil
		}
	}

	ui.PrintSuccess("Found %d DataDescriptor(s)", len(descriptors))
	fmt.Println()

	// Step 2: Collect DAC information
	var name, description string

	// Name
	namePrompt := &survey.Input{
		Message: "DataAgentContainer name:",
		Help:    "lowercase letters, numbers and hyphens only",
	}
	if err := survey.AskOne(namePrompt, &name, survey.WithValidator(survey.Required)); err != nil {
		return fmt.Errorf("input cancelled")
	}

	// Description (optional)
	descPrompt := &survey.Input{
		Message: "Agent description (optional):",
		Help:    "brief description of this agent's purpose",
	}
	if err := survey.AskOne(descPrompt, &description); err != nil {
		return fmt.Errorf("input cancelled")
	}

	// Use default description if empty
	if description == "" {
		description = fmt.Sprintf("Data Agent for %s", name)
	}

	// Step 3: Select data sources
	ddOptions := make([]string, len(descriptors))
	for i, dd := range descriptors {
		ddOptions[i] = fmt.Sprintf("%s (%s)", dd.Name, dd.DescriptorType)
	}

	var selectedDDs []string
	ddPrompt := &survey.MultiSelect{
		Message: "Select data sources (space to select, enter to confirm):",
		Options: ddOptions,
	}
	if err := survey.AskOne(ddPrompt, &selectedDDs); err != nil {
		return fmt.Errorf("selection cancelled")
	}

	if len(selectedDDs) == 0 {
		ui.PrintError("At least one data source must be selected")
		return fmt.Errorf("no data source selected")
	}

	// Extract DD names from selections
	ddNames := make([]string, len(selectedDDs))
	for i, sel := range selectedDDs {
		// Extract name from "name (type)" format
		parts := strings.Split(sel, " (")
		ddNames[i] = parts[0]
	}

	// Step 4: Select model preset
	modelOptions := []string{
		"Qwen Max (qwen-max + text-embedding-v3) - recommended",
		"Qwen Plus (qwen-plus + text-embedding-v2)",
		"Qwen Turbo (qwen-turbo + text-embedding-v2) - economical",
	}
	var selectedModel string
	modelPrompt := &survey.Select{
		Message: "Select model preset:",
		Options: modelOptions,
		Default: modelOptions[0],
	}
	if err := survey.AskOne(modelPrompt, &selectedModel); err != nil {
		return fmt.Errorf("selection cancelled")
	}

	// Build model spec based on selection
	var modelSpec types.ModelSpec
	if strings.Contains(selectedModel, "Qwen Max") {
		modelSpec.ExpertLLM = "qwen-max"
		modelSpec.PlannerLLM = "qwen-max"
		modelSpec.Embedding = "text-embedding-v3"
	} else if strings.Contains(selectedModel, "Qwen Plus") {
		modelSpec.ExpertLLM = "qwen-plus"
		modelSpec.PlannerLLM = "qwen-plus"
		modelSpec.Embedding = "text-embedding-v2"
	} else {
		modelSpec.ExpertLLM = "qwen-turbo"
		modelSpec.PlannerLLM = "qwen-turbo"
		modelSpec.Embedding = "text-embedding-v2"
	}

	// Step 5: Expert Agent Max Steps
	var maxStepsInput string
	maxStepsPrompt := &survey.Input{
		Message: "Expert Agent max steps (default: 5):",
		Default: "5",
		Help:    "maximum iteration steps for agent task execution",
	}
	if err := survey.AskOne(maxStepsPrompt, &maxStepsInput); err != nil {
		return fmt.Errorf("input cancelled")
	}

	// Build create request
	req := &types.CreateDACRequest{
		Name:      name,
		Namespace: namespace,
		DataPolicy: types.DataPolicy{
			SourceNameSelector: ddNames,
		},
		AgentCard: types.AgentCard{
			Name:        name,
			Description: description,
			Skills:      []types.AgentSkill{},
		},
		Model:               modelSpec,
		ExpertAgentMaxSteps: maxStepsInput,
	}

	// Confirm creation
	ui.PrintInfo("About to create DataAgentContainer:")
	fmt.Printf("  Name: %s\n", name)
	fmt.Printf("  Namespace: %s\n", namespace)
	fmt.Printf("  Description: %s\n", description)
	fmt.Printf("  Data Sources: %v\n", ddNames)
	fmt.Printf("  Model: %s / %s\n", req.Model.ExpertLLM, req.Model.Embedding)
	fmt.Printf("  Max Steps: %s\n", maxStepsInput)
	fmt.Println()

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

	// Create the resource
	ui.PrintInfo("Creating...")
	if err := apiClient.CreateAgentContainer(ctx, req); err != nil {
		ui.PrintError("Failed to create: %v", err)
		return fmt.Errorf("creation failed")
	}

	ui.PrintSuccess("DataAgentContainer '%s' created successfully!", name)
	fmt.Println()
	fmt.Printf("View resource: dactl list -n %s\n", namespace)

	return nil
}

