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
	loginUsername string
)

// loginCmd is the login command
var loginCmd = &cobra.Command{
	Use:   "login [server]",
	Short: "authenticate with DAC API server",
	Long: `Authenticate with DAC API Server and save credentials locally.

Your authentication token will be stored in ~/.dactl/config.yaml and used
automatically for all subsequent commands. The token remains valid until
it expires or you login again.

If server is not provided, defaults to http://localhost:8080.`,
	Example: `  # Login to default server (localhost:8080)
  $ dactl login

  # Login to custom server
  $ dactl login http://api.example.com:8080

  # Login with username (will prompt for password)
  $ dactl login http://api.example.com:8080 -u admin`,
	Args: cobra.MaximumNArgs(1), // Allow 0 or 1 server argument
	RunE: runLogin,
}

func init() {
	loginCmd.Flags().StringVarP(&loginUsername, "username", "u", "", "Username for authentication")

	// Silence usage to avoid showing help on every error
	loginCmd.SilenceUsage = true
}

func runLogin(cmd *cobra.Command, args []string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Get server from position argument or use default
	loginServer := "http://localhost:8080"
	if len(args) > 0 {
		loginServer = args[0]
	}

	// 1. Prompt for username if not provided
	if loginUsername == "" {
		prompt := &survey.Input{
			Message: "Username:",
		}
		if err := survey.AskOne(prompt, &loginUsername, survey.WithValidator(survey.Required)); err != nil {
			ui.PrintError("failed to read username: %v", err)
			return fmt.Errorf("input failed")
		}
	}

	// 2. Prompt for password (hidden input)
	var password string
	prompt := &survey.Password{
		Message: "Password:",
	}
	if err := survey.AskOne(prompt, &password, survey.WithValidator(survey.Required)); err != nil {
		ui.PrintError("failed to read password: %v", err)
		return fmt.Errorf("input failed")
	}

	// 3. Create API client
	apiClient, err := client.NewAPIClient(loginServer, "")
	if err != nil {
		ui.PrintError("failed to create client: %v", err)
		return fmt.Errorf("client creation failed")
	}

	ui.PrintInfo("Connecting to %s...", loginServer)

	// 4. Call login API
	resp, err := apiClient.Login(ctx, loginUsername, password)
	if err != nil {
		ui.PrintErrorBox("Login Failed", err.Error())
		return fmt.Errorf("authentication failed")
	}

	// 5. Save config to local file
	cfg := &config.Config{
		Server:      loginServer,
		AccessToken: resp.Data.Token,
		Username:    resp.Data.User.Username,
		UserID:      resp.Data.User.ID,
	}

	if err := cfg.Save(); err != nil {
		ui.PrintError("failed to save config: %v", err)
		return fmt.Errorf("config save failed")
	}

	// 6. Display success message
	configPath, _ := config.GetConfigPath()
	successContent := fmt.Sprintf(`Username:       %s
User ID:        %s
Token expires:  %s
Config saved:   %s`,
		resp.Data.User.Username,
		resp.Data.User.ID,
		resp.Data.Expire,
		configPath,
	)

	ui.PrintSuccessBox("✓ Login Successful", successContent)

	// 7. Display usage hints
	fmt.Println()
	ui.PrintInfo("You can now use the following commands:")
	ui.PrintBold("  dactl list              # List all resources")
	ui.PrintBold("  dactl describe <name>   # Show resource details")

	return nil
}

// trimServer removes trailing slashes from server address
func trimServer(server string) string {
	return strings.TrimRight(server, "/")
}
