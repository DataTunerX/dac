pub struct RetrievalLocatorRef {
    pub source_id: String,     // "ehr_a"
    pub locator_ref: String,   // "cholesterol_total_v3"
    pub access_method: String, // "sql" | "fhir" | "api"
}

pub struct SemanticBindingContract {
    pub binding_id: String,
    pub dac_id: String,
    pub local_term: String,
    pub ontology_anchor: String, // canonical concept id
    pub unit: Option<String>,
    pub data_type: String,
    pub confidence: f32,
    pub status: BindingStatus,
    pub bitemporal: Bitemporal,
    pub locator: RetrievalLocatorRef, // opaque; not interpreted by ontology engine
}
