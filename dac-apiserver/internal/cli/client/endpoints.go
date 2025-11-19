package client

const (
	// API version prefix
	apiV1Prefix = "/api/v1"

	// Authentication endpoints
	endpointLogin = apiV1Prefix + "/auth/login"

	// Agent Container endpoints
	endpointAgentsAll              = apiV1Prefix + "/agents"                  // GET - list all namespaces
	endpointAgentsNamespaced       = apiV1Prefix + "/namespaces/%s/agents"    // GET, POST
	endpointAgentsNamespacedByName = apiV1Prefix + "/namespaces/%s/agents/%s" // GET, PUT, DELETE

	// Data Descriptor endpoints
	endpointDescriptorsAll              = apiV1Prefix + "/descriptors"                  // GET - list all namespaces
	endpointDescriptorsNamespaced       = apiV1Prefix + "/namespaces/%s/descriptors"    // GET, POST
	endpointDescriptorsNamespacedByName = apiV1Prefix + "/namespaces/%s/descriptors/%s" // GET, PUT, DELETE

	// Chat endpoints
	endpointChatCompletions = "/v1/chat/completions" // OpenAI-compatible endpoint
)
