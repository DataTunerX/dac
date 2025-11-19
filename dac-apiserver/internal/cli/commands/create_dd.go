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
	// DataDescriptor flags
	ddName     string
	ddType     string
	ddHost     string
	ddPort     string
	ddDatabase string
	ddUsername string
	ddPassword string
	ddTables   string
)

// createDDCmd is the DataDescriptor create subcommand
var createDDCmd = &cobra.Command{
	Use:     "dd",
	Aliases: []string{"datadescriptor"},
	Short:   "Create a DataDescriptor",
	Long: `Create a DataDescriptor resource for configuring data sources.

A DataDescriptor defines how to connect to and extract data from various sources
like databases (MySQL, PostgreSQL), object storage (MinIO), or file servers.

You can create a DataDescriptor in two ways:
  1. Interactive mode (will prompt for all required fields)
  2. Non-interactive mode using command-line flags`,
	Example: `  # Interactive creation (will prompt for details)
  $ dactl create dd

  # Create MySQL DataDescriptor with flags
  $ dactl create dd --name my-mysql-db \
    --type mysql \
    --host localhost \
    --port 3306 \
    --database mydb \
    --username admin \
    --password secret \
    --tables users,orders,products

  # Create PostgreSQL DataDescriptor
  $ dactl create dd --name my-postgres \
    --type postgres \
    --host db.example.com \
    --port 5432 \
    --database analytics \
    --username readonly

  # Create in specific namespace
  $ dactl create dd -n production --name prod-db --type mysql --host prod.db.internal`,
	RunE: runCreateDD,
}

func init() {
	// DataDescriptor-specific flags
	createDDCmd.Flags().StringVar(&ddName, "name", "", "DataDescriptor name (required for non-interactive mode)")
	createDDCmd.Flags().StringVar(&ddType, "type", "", "Data source type: mysql, postgres, minio, fileserver")
	createDDCmd.Flags().StringVar(&ddHost, "host", "", "Database or service host address")
	createDDCmd.Flags().StringVar(&ddPort, "port", "", "Database or service port (auto-detected if not specified)")
	createDDCmd.Flags().StringVar(&ddDatabase, "database", "", "Database name (for relational databases)")
	createDDCmd.Flags().StringVar(&ddUsername, "username", "", "Database username")
	createDDCmd.Flags().StringVar(&ddPassword, "password", "", "Database password")
	createDDCmd.Flags().StringVar(&ddTables, "tables", "", "Comma-separated list of tables to extract (leave empty for all)")
}

func runCreateDD(cmd *cobra.Command, args []string) error {
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
	if ddName != "" && ddType != "" && ddHost != "" {
		return createDataDescriptorFromFlags(ctx, apiClient, createNamespace)
	}

	// Interactive mode
	return createDataDescriptorInteractive(ctx, apiClient, createNamespace)
}

// createDataDescriptorFromFlags creates DataDescriptor from command-line flags (non-interactive)
func createDataDescriptorFromFlags(ctx context.Context, apiClient *client.APIClient, namespace string) error {
	// Set default port if not provided
	if ddPort == "" {
		ddPort = getDefaultPort(ddType)
	}

	// Build metadata
	metadata := make(map[string]string)
	metadata["host"] = ddHost
	metadata["port"] = ddPort
	if ddDatabase != "" {
		metadata["database"] = ddDatabase
	}
	if ddUsername != "" {
		metadata["username"] = ddUsername
	}
	if ddPassword != "" {
		metadata["password"] = ddPassword
	}

	// Build data source
	dataSource := types.DataSource{
		Type:     ddType,
		Name:     fmt.Sprintf("%s-source", ddName),
		Metadata: metadata,
	}

	// Parse tables if provided
	if ddTables != "" {
		tables := strings.Split(ddTables, ",")
		for i := range tables {
			tables[i] = strings.TrimSpace(tables[i])
		}
		dataSource.Extract = &types.ExtractConfig{
			Tables: tables,
		}
	}

	// Build create request
	req := &types.CreateDDRequest{
		Name:           ddName,
		Namespace:      namespace,
		DescriptorType: ddType,
		Sources:        []types.DataSource{dataSource},
	}

	// Display configuration
	ui.PrintInfo("Creating DataDescriptor:")
	fmt.Printf("  Name: %s\n", req.Name)
	fmt.Printf("  Namespace: %s\n", req.Namespace)
	fmt.Printf("  Type: %s\n", req.DescriptorType)
	fmt.Printf("  Host: %s:%s\n", ddHost, ddPort)
	if ddDatabase != "" {
		fmt.Printf("  Database: %s\n", ddDatabase)
	}
	if ddTables != "" {
		fmt.Printf("  Tables: %s\n", ddTables)
	}
	fmt.Println()

	// Create the resource
	ui.PrintInfo("Creating...")
	if err := apiClient.CreateDataDescriptor(ctx, req); err != nil {
		ui.PrintError("Failed to create: %v", err)
		return fmt.Errorf("creation failed")
	}

	ui.PrintSuccess("DataDescriptor '%s' created successfully!", ddName)
	fmt.Println()
	fmt.Printf("View resource: dactl list -n %s\n", namespace)

	return nil
}

// createDataDescriptorInteractive guides user through DD creation (interactive mode)
func createDataDescriptorInteractive(ctx context.Context, apiClient *client.APIClient, namespace string) error {
	ui.PrintInfo("Creating DataDescriptor (Interactive Mode)")
	fmt.Println()

	// Step 1: Collect DD name
	var name string
	namePrompt := &survey.Input{
		Message: "DataDescriptor name:",
		Help:    "lowercase letters, numbers and hyphens only",
	}
	if err := survey.AskOne(namePrompt, &name, survey.WithValidator(survey.Required)); err != nil {
		return fmt.Errorf("input cancelled")
	}

	// Step 2: Select data source type
	sourceTypeOptions := []string{
		"mysql",
		"postgres",
		"minio",
		"fileserver",
	}
	var sourceType string
	typePrompt := &survey.Select{
		Message: "Select data source type:",
		Options: sourceTypeOptions,
	}
	if err := survey.AskOne(typePrompt, &sourceType); err != nil {
		return fmt.Errorf("selection cancelled")
	}

	// Step 3: Collect data source name
	var sourceName string
	sourceNamePrompt := &survey.Input{
		Message: "Data source name:",
		Default: fmt.Sprintf("%s-source", name),
	}
	if err := survey.AskOne(sourceNamePrompt, &sourceName, survey.WithValidator(survey.Required)); err != nil {
		return fmt.Errorf("input cancelled")
	}

	// Step 4: Collect connection information
	metadata := make(map[string]string)

	// Host
	var host string
	hostPrompt := &survey.Input{
		Message: "Host:",
		Default: "localhost",
	}
	if err := survey.AskOne(hostPrompt, &host, survey.WithValidator(survey.Required)); err != nil {
		return fmt.Errorf("input cancelled")
	}
	metadata["host"] = host

	// Port
	var port string
	portDefault := getDefaultPort(sourceType)
	portPrompt := &survey.Input{
		Message: "Port:",
		Default: portDefault,
	}
	if err := survey.AskOne(portPrompt, &port, survey.WithValidator(survey.Required)); err != nil {
		return fmt.Errorf("input cancelled")
	}
	metadata["port"] = port

	// Database name (for relational databases)
	if sourceType == "mysql" || sourceType == "postgres" {
		var database string
		dbPrompt := &survey.Input{
			Message: "Database name:",
		}
		if err := survey.AskOne(dbPrompt, &database, survey.WithValidator(survey.Required)); err != nil {
			return fmt.Errorf("input cancelled")
		}
		metadata["database"] = database
	}

	// Username
	var username string
	userPrompt := &survey.Input{
		Message: "Username:",
	}
	if err := survey.AskOne(userPrompt, &username); err != nil {
		return fmt.Errorf("input cancelled")
	}
	if username != "" {
		metadata["username"] = username
	}

	// Password (masked)
	var password string
	passPrompt := &survey.Password{
		Message: "Password:",
	}
	if err := survey.AskOne(passPrompt, &password); err != nil {
		return fmt.Errorf("input cancelled")
	}
	if password != "" {
		metadata["password"] = password
	}

	// Step 5: Collect table/collection names (for databases)
	var tables []string
	if sourceType == "mysql" || sourceType == "postgres" {
		var tablesInput string
		tablesPrompt := &survey.Input{
			Message: "Tables to extract (comma-separated, leave empty for all):",
			Help:    "e.g.: users,orders,products",
		}
		if err := survey.AskOne(tablesPrompt, &tablesInput); err != nil {
			return fmt.Errorf("input cancelled")
		}
		if tablesInput != "" {
			tables = strings.Split(tablesInput, ",")
			for i := range tables {
				tables[i] = strings.TrimSpace(tables[i])
			}
		}
	}

	// Build data source
	dataSource := types.DataSource{
		Type:     sourceType,
		Name:     sourceName,
		Metadata: metadata,
	}

	if len(tables) > 0 {
		dataSource.Extract = &types.ExtractConfig{
			Tables: tables,
		}
	}

	// Build create request
	req := &types.CreateDDRequest{
		Name:           name,
		Namespace:      namespace,
		DescriptorType: sourceType,
		Sources:        []types.DataSource{dataSource},
	}

	// Confirm creation
	ui.PrintInfo("About to create DataDescriptor:")
	fmt.Printf("  Name: %s\n", name)
	fmt.Printf("  Namespace: %s\n", namespace)
	fmt.Printf("  Type: %s\n", sourceType)
	fmt.Printf("  Data Source: %s\n", sourceName)
	fmt.Printf("  Connection: %s:%s\n", host, port)
	if len(tables) > 0 {
		fmt.Printf("  Tables: %v\n", tables)
	}
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
	if err := apiClient.CreateDataDescriptor(ctx, req); err != nil {
		ui.PrintError("Failed to create: %v", err)
		return fmt.Errorf("creation failed")
	}

	ui.PrintSuccess("DataDescriptor '%s' created successfully!", name)
	fmt.Println()
	fmt.Printf("View resource: dactl list -n %s\n", namespace)

	return nil
}

