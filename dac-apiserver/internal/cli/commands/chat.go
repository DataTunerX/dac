package commands

import (
	"fmt"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/lvyanru/dac-apiserver/internal/cli/client"
	"github.com/lvyanru/dac-apiserver/internal/cli/config"
	"github.com/lvyanru/dac-apiserver/internal/cli/tui"
	"github.com/lvyanru/dac-apiserver/internal/cli/ui"
)

// chatCmd is the chat command
var chatCmd = &cobra.Command{
	Use:   "chat",
	Short: "start interactive chat with Data Agent",
	Long: `Start an interactive chat session with Data Agent Container.

Features:
  • 实时流式输出
  • 多轮对话上下文manage
  • 终端 TUI，贴近 Claude Code 体验`,
	Example: `  # Start interactive chat
  $ dactl chat

  # Keyboard controls:
  • 输入消息按 Enter 发送
  • Esc 退出会话`,
	RunE: runChat,
}

func init() {
	chatCmd.SilenceUsage = true
}

func runChat(cmd *cobra.Command, args []string) error {
	if len(args) > 0 {
		ui.PrintError("unexpected argument: %s", args[0])
		fmt.Println("\nRun 'dactl chat' to start interactive session.")
		return fmt.Errorf("invalid arguments")
	}

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

	apiClient, err := client.NewAPIClient(cfg.Server, cfg.AccessToken)
	if err != nil {
		ui.PrintError("failed to create client: %v", err)
		return fmt.Errorf("client creation failed")
	}

	runID := generateRunID()
	program := tui.NewChatProgram(apiClient, runID)
	if err := program.Run(); err != nil {
		return fmt.Errorf("failed to run chat TUI: %w", err)
	}

	return nil
}

func generateRunID() string {
	return uuid.New().String()
}
