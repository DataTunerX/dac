package ui

import (
	"fmt"

	"github.com/charmbracelet/lipgloss"
	"github.com/charmbracelet/lipgloss/tree"
	"github.com/fatih/color"

	"github.com/lvyanru/dac-apiserver/internal/cli/types"
)

var (
	// Tree node styles
	dacStyle       = lipgloss.NewStyle().Foreground(lipgloss.Color("86")).Bold(true)  // Cyan
	ddStyle        = lipgloss.NewStyle().Foreground(lipgloss.Color("39"))             // Blue
	keyStyle       = lipgloss.NewStyle().Foreground(lipgloss.Color("245"))            // Gray
	valueStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("229"))            // Yellow
	highlightStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("212")).Bold(true) // Pink

	// Title style with border
	titleStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("86")).
			Bold(true).
			MarginTop(1).
			MarginBottom(1)

	// Summary box style
	summaryStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("245")).
			MarginTop(1)
)

// RenderResourceTree renders DataAgentContainers and DataDescriptors as a tree
// If showNamespace is true, wraps resources in a namespace root node
func RenderResourceTree(agents []types.AgentContainer, descriptors []types.DataDescriptor, namespace string, showNamespace bool) string {
	if len(agents) == 0 && len(descriptors) == 0 {
		emptyMsg := keyStyle.Render("No resources found")
		return emptyMsg
	}

	var output string

	// Track which DDs are used
	usedDDs := make(map[string]bool)

	// Build DAC nodes
	var dacTrees []*tree.Tree
	for _, agent := range agents {
		dacNode := buildDACNode(agent, descriptors)
		dacTrees = append(dacTrees, dacNode)

		// Mark DDs as used (from spec, not status)
		for _, ddName := range agent.DataPolicy.SourceNameSelector {
			key := fmt.Sprintf("%s/%s", agent.Namespace, ddName)
			usedDDs[key] = true
		}
	}

	// Get orphaned DDs
	orphanedDDs := getOrphanedDescriptors(descriptors, usedDDs)

	// If showNamespace, wrap in namespace root
	if showNamespace && namespace != "" {
		rootLabel := fmt.Sprintf("Namespace: %s", highlightStyle.Render(namespace))
		root := tree.Root(rootLabel)
		for _, dacTree := range dacTrees {
			root.Child(dacTree)
		}
		output = root.String()

		// Append orphaned DDs as a simple list (not tree)
		if len(orphanedDDs) > 0 {
			output += "\n\n" + renderOrphanedDescriptorList(orphanedDDs)
		}
		return output
	}

	// Otherwise, render DACs at root level
	for i, dacTree := range dacTrees {
		output += dacTree.String()
		if i < len(dacTrees)-1 {
			output += "\n"
		}
	}

	// Append orphaned DDs as a simple list (not tree)
	if len(orphanedDDs) > 0 {
		if len(dacTrees) > 0 {
			output += "\n\n"
		}
		output += renderOrphanedDescriptorList(orphanedDDs)
	}

	return output
}

// buildDACNode creates a tree node for a DataAgentContainer
func buildDACNode(agent types.AgentContainer, descriptors []types.DataDescriptor) *tree.Tree {
	// DAC header with endpoint
	endpoint := ""
	if agent.Endpoint != nil && agent.Endpoint.Address != "" {
		endpoint = keyStyle.Render(fmt.Sprintf(" (%s:%d)", agent.Endpoint.Address, agent.Endpoint.Port))
	}

	dacLabel := fmt.Sprintf("%s%s",
		dacStyle.Render(agent.Name),
		endpoint,
	)

	dacTree := tree.New().Root(dacLabel)

	// Add DataDescriptors
	// Show DDs from spec (configured references), with status from status (actual state)
	if len(agent.DataPolicy.SourceNameSelector) == 0 {
		dacTree.Child(keyStyle.Render("(no data descriptors)"))
		return dacTree
	}

	// Build a map of active DDs from status for quick lookup
	activeDDMap := make(map[string]bool)
	for _, activeDD := range agent.ActiveDataDescriptors {
		key := fmt.Sprintf("%s/%s", activeDD.Namespace, activeDD.Name)
		activeDDMap[key] = true
	}

	// Show each DD from spec
	for _, ddName := range agent.DataPolicy.SourceNameSelector {
		// Find the descriptor
		var foundDesc *types.DataDescriptor
		for _, desc := range descriptors {
			if desc.Name == ddName && desc.Namespace == agent.Namespace {
				foundDesc = &desc
				break
			}
		}

		// Check if it's active in status
		key := fmt.Sprintf("%s/%s", agent.Namespace, ddName)
		isActive := activeDDMap[key]

		if foundDesc != nil {
			ddNode := buildDDNodeWithStatus(*foundDesc, isActive)
			dacTree.Child(ddNode)
		} else {
			// DD referenced but not found
			pendingLabel := fmt.Sprintf("%s %s",
				ddStyle.Render(ddName),
				keyStyle.Render("(not found)"))
			dacTree.Child(pendingLabel)
		}
	}

	return dacTree
}

// buildDDNodeWithStatus creates a tree node for a DataDescriptor with status indicator
func buildDDNodeWithStatus(desc types.DataDescriptor, isActive bool) *tree.Tree {
	// Add status indicator to name
	statusIndicator := ""
	if !isActive {
		statusIndicator = " " + keyStyle.Render("(initializing...)")
	}

	ddLabel := ddStyle.Render(desc.Name) + statusIndicator
	ddTree := tree.New().Root(ddLabel)

	// Type
	ddType := desc.DescriptorType
	if ddType == "" {
		ddType = "unknown"
	}
	ddTree.Child(formatKeyValue("Type:", ddType))

	// Database info (from metadata)
	if len(desc.Sources) > 0 && desc.Sources[0].Metadata != nil {
		metadata := desc.Sources[0].Metadata
		if db, ok := metadata["database"]; ok {
			host := metadata["host"]
			port := metadata["port"]
			dbInfo := fmt.Sprintf("%s@%s:%s", db, host, port)
			ddTree.Child(formatKeyValue("Database:", dbInfo))
		}
	}

	// Phase with status (only if active)
	if isActive {
		phase := desc.OverallPhase
		if phase == "" {
			phase = "Unknown"
		}

		phaseValue := getColoredPhase(phase)

		// Add status info if available
		if len(desc.SourceStatuses) > 0 {
			status := desc.SourceStatuses[0]
			if status.Phase == "Error" || phase == "NotReady" {
				phaseValue = fmt.Sprintf("%s (%s)", phaseValue, color.RedString(status.Phase))
			} else if status.Records > 0 {
				phaseValue = fmt.Sprintf("%s (%d records)", phaseValue, status.Records)
			}
		}

		ddTree.Child(formatKeyValue("Status:", phaseValue))
	}

	return ddTree
}

// buildDDNode creates a tree node for a DataDescriptor (for orphaned DDs)
func buildDDNode(desc types.DataDescriptor) *tree.Tree {
	ddLabel := ddStyle.Render(desc.Name)
	ddTree := tree.New().Root(ddLabel)

	// Type
	ddType := desc.DescriptorType
	if ddType == "" {
		ddType = "unknown"
	}
	ddTree.Child(formatKeyValue("Type:", ddType))

	// Database info (from metadata)
	if len(desc.Sources) > 0 && desc.Sources[0].Metadata != nil {
		metadata := desc.Sources[0].Metadata
		if db, ok := metadata["database"]; ok {
			host := metadata["host"]
			port := metadata["port"]
			dbInfo := fmt.Sprintf("%s@%s:%s", db, host, port)
			ddTree.Child(formatKeyValue("Database:", dbInfo))
		}
	}

	// Phase with status
	phase := desc.OverallPhase
	if phase == "" {
		phase = "Unknown"
	}

	phaseValue := getColoredPhase(phase)

	// Add status info if available
	if len(desc.SourceStatuses) > 0 {
		status := desc.SourceStatuses[0]
		if status.Phase == "Error" || phase == "NotReady" {
			phaseValue = fmt.Sprintf("%s (%s)", phaseValue, color.RedString(status.Phase))
		} else if status.Records > 0 {
			phaseValue = fmt.Sprintf("%s (%d records)", phaseValue, status.Records)
		}
	}

	ddTree.Child(formatKeyValue("Status:", phaseValue))

	return ddTree
}

// formatKeyValue formats a key-value pair
func formatKeyValue(key, value string) string {
	return fmt.Sprintf("%s %s",
		keyStyle.Render(key),
		value,
	)
}

// getColoredPhase returns a colored phase string
func getColoredPhase(phase string) string {
	switch phase {
	case "Ready", "Active":
		return color.GreenString(phase)
	case "Pending", "Processing":
		return color.YellowString(phase)
	case "Failed", "Error", "NotReady":
		return color.RedString(phase)
	default:
		return phase
	}
}

// getOrphanedDescriptors returns descriptors not used by any DAC
func getOrphanedDescriptors(descriptors []types.DataDescriptor, usedDDs map[string]bool) []types.DataDescriptor {
	var orphaned []types.DataDescriptor

	for _, desc := range descriptors {
		key := fmt.Sprintf("%s/%s", desc.Namespace, desc.Name)
		if !usedDDs[key] {
			orphaned = append(orphaned, desc)
		}
	}

	return orphaned
}

// RenderResourceTreeGroupedByNamespace renders resources grouped by namespace
func RenderResourceTreeGroupedByNamespace(agents []types.AgentContainer, descriptors []types.DataDescriptor) string {
	if len(agents) == 0 && len(descriptors) == 0 {
		emptyMsg := keyStyle.Render("No resources found")
		return emptyMsg
	}

	var output string

	// Group resources by namespace
	namespaceMap := make(map[string]struct {
		agents      []types.AgentContainer
		descriptors []types.DataDescriptor
	})

	for _, agent := range agents {
		entry := namespaceMap[agent.Namespace]
		entry.agents = append(entry.agents, agent)
		namespaceMap[agent.Namespace] = entry
	}

	for _, desc := range descriptors {
		entry := namespaceMap[desc.Namespace]
		entry.descriptors = append(entry.descriptors, desc)
		namespaceMap[desc.Namespace] = entry
	}

	// Render each namespace
	first := true
	for ns, resources := range namespaceMap {
		if !first {
			output += "\n\n"
		}
		first = false

		// Render namespace group with showNamespace=true
		nsOutput := RenderResourceTree(resources.agents, resources.descriptors, ns, true)
		output += nsOutput
	}

	return output
}

// renderOrphanedDescriptorList renders orphaned DDs as a simple list (not tree)
func renderOrphanedDescriptorList(descriptors []types.DataDescriptor) string {
	if len(descriptors) == 0 {
		return ""
	}

	// First pass: collect data and calculate max widths
	type rowData struct {
		name        string
		ddType      string
		dbInfo      string
		statusText  string
		statusColor string
	}

	var rows []rowData
	maxNameLen := 0
	maxTypeLen := 0
	maxDBLen := 0

	for _, desc := range descriptors {
		// Name
		name := desc.Name
		if len(name) > maxNameLen {
			maxNameLen = len(name)
		}

		// Type
		ddType := desc.DescriptorType
		if ddType == "" {
			ddType = "unknown"
		}
		if len(ddType) > maxTypeLen {
			maxTypeLen = len(ddType)
		}

		// Database info
		dbInfo := ""
		if len(desc.Sources) > 0 && desc.Sources[0].Metadata != nil {
			metadata := desc.Sources[0].Metadata
			if db, ok := metadata["database"]; ok {
				host := metadata["host"]
				port := metadata["port"]
				dbInfo = fmt.Sprintf("%s@%s:%s", db, host, port)
			}
		}
		if len(dbInfo) > maxDBLen {
			maxDBLen = len(dbInfo)
		}

		// Status
		phase := desc.OverallPhase
		if phase == "" {
			phase = "Unknown"
		}
		statusDetail := ""
		if len(desc.SourceStatuses) > 0 {
			status := desc.SourceStatuses[0]
			if status.Phase != "" {
				statusDetail = fmt.Sprintf(" (%s)", status.Phase)
			}
		}

		rows = append(rows, rowData{
			name:        name,
			ddType:      ddType,
			dbInfo:      dbInfo,
			statusText:  phase + statusDetail,
			statusColor: phase,
		})
	}

	// Second pass: render with dynamic widths
	var output string
	header := color.YellowString("Unused DataDescriptors:")
	output += header + "\n"

	for _, row := range rows {
		statusStr := getColoredPhase(row.statusColor)
		if len(row.statusText) > len(row.statusColor) {
			statusStr += row.statusText[len(row.statusColor):]
		}

		output += fmt.Sprintf("  • %-*s  |  %-*s  |  %-*s  |  %s\n",
			maxNameLen, row.name,
			maxTypeLen, row.ddType,
			maxDBLen, row.dbInfo,
			statusStr)
	}

	return output
}

// RenderResourceSummary renders a summary line with better formatting
func RenderResourceSummary(dacCount, ddCount int) string {
	dacLabel := "DataAgentContainers"
	if dacCount == 1 {
		dacLabel = "DataAgentContainer"
	}
	ddLabel := "DataDescriptors"
	if ddCount == 1 {
		ddLabel = "DataDescriptor"
	}

	summary := fmt.Sprintf("Total: %s %s, %s %s",
		highlightStyle.Render(fmt.Sprintf("%d", dacCount)),
		keyStyle.Render(dacLabel),
		highlightStyle.Render(fmt.Sprintf("%d", ddCount)),
		keyStyle.Render(ddLabel),
	)

	return summaryStyle.Render(summary)
}
