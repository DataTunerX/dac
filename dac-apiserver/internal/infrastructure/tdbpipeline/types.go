package tdbpipeline

// Wire types for the TDB pipeline controller API. Field names follow the
// controller's camelCase contract (see tdb/docs/tdb_pipeline_controller_runbook.md,
// "Part 2: Use The Controller API") and are deliberately kept separate from the
// domain types so a controller contract change stays contained here.

type sourceWire struct {
	Type      string `json:"type"`
	URI       string `json:"uri,omitempty"`
	ClaimName string `json:"claimName,omitempty"`
	Path      string `json:"path,omitempty"`
}

type targetWire struct {
	GatewayURL      string `json:"gatewayUrl"`
	Domain          string `json:"domain"`
	KnowledgeDomain string `json:"knowledgeDomain"`
	DomainProfile   string `json:"domainProfile"`
}

type optionsWire struct {
	LLMProfile                    string `json:"llmProfile,omitempty"`
	GenerateQA                    *bool  `json:"generateQa,omitempty"`
	AutoEval                      *bool  `json:"autoEval,omitempty"`
	LLMGrade                      *bool  `json:"llmGrade,omitempty"`
	OpenLayerPredicateMergeEvery  *int   `json:"openLayerPredicateMergeEvery,omitempty"`
	OpenLayerPredicateAutopromote *bool  `json:"openLayerPredicateAutopromote,omitempty"`
	MaxConcurrent                 *int   `json:"maxConcurrent,omitempty"`
	StartStaggerSeconds           *int   `json:"startStaggerSeconds,omitempty"`
	StartStaggerJitterSeconds     *int   `json:"startStaggerJitterSeconds,omitempty"`
	QuestionWorkers               *int   `json:"questionWorkers,omitempty"`
	QuestionRepairTimeoutSeconds  *int   `json:"questionRepairTimeoutSeconds,omitempty"`
}

type artifactUploadWire struct {
	RunsPrefix          string `json:"runsPrefix"`
	StatusPrefix        string `json:"statusPrefix"`
	AttemptStatusPrefix string `json:"attemptStatusPrefix,omitempty"`
	Strict              *bool  `json:"strict,omitempty"`
}

type callbackWire struct {
	URL    string   `json:"url"`
	Events []string `json:"events,omitempty"`
}

type createRunWire struct {
	Source         sourceWire         `json:"source"`
	Collection     string             `json:"collection"`
	Image          string             `json:"image"`
	Target         targetWire         `json:"target"`
	Options        *optionsWire       `json:"options,omitempty"`
	ArtifactUpload artifactUploadWire `json:"artifactUpload"`
	Callback       *callbackWire      `json:"callback,omitempty"`
	Metadata       map[string]any     `json:"metadata,omitempty"`
}

type createRunAckWire struct {
	RunID     string `json:"runId"`
	Status    string `json:"status"`
	StatusURL string `json:"statusUrl"`
}

type runSummaryWire struct {
	RunID     string `json:"runId"`
	Status    string `json:"status"`
	TotalJobs int    `json:"totalJobs"`
	Queued    int    `json:"queued"`
	Starting  int    `json:"starting"`
	Running   int    `json:"running"`
	Uploading int    `json:"uploading"`
	Succeeded int    `json:"succeeded"`
	Failed    int    `json:"failed"`
	Canceled  int    `json:"canceled"`
}

type actionResultWire struct {
	RunID            string   `json:"runId"`
	Status           string   `json:"status"`
	DeletedJobs      []string `json:"deletedJobs"`
	RetriedJobs      int      `json:"retriedJobs"`
	RequestedUploads int      `json:"requestedUploads"`
}

type retryFailedWire struct {
	FailedStage string `json:"failedStage,omitempty"`
}

// errorWire is the controller's error body. Both shapes have been observed
// depending on whether FastAPI or the controller itself rejected the request.
type errorWire struct {
	Detail  string `json:"detail"`
	Message string `json:"message"`
}
