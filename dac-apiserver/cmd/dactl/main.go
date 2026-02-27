package main

import (
	"os"
	"strings"

	"github.com/lvyanru/dac-apiserver/internal/cli/commands"
	"github.com/lvyanru/dac-apiserver/internal/cli/ui"
)

func main() {
	if err := commands.Execute(); err != nil {
		// Handle unknown command errors specially
		errMsg := err.Error()
		if strings.Contains(errMsg, "unknown command") {
			ui.PrintError("%s", errMsg)
			ui.PrintInfo("Run 'dactl --help' for usage.")
		}
		os.Exit(1)
	}
}