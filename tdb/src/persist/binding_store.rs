/*
semantic_binding_contract table

binding_id (PK)

dac_id

local_term

ontology_anchor

unit

data_type

confidence

effective_from, effective_to

system_time

status (draft/approved/deprecated)

created_at, approved_by

DAC shall provide:
bindings:
  - local_term: "cholesterol_total"
    ontology_anchor: "medical.lab.lipid.total_cholesterol"
    unit: "mg/dL"
    data_type: numeric
    confidence: 0.98
    valid_from: 2024-01-01
*/