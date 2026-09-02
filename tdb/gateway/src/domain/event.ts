export const EVENT_TYPES = [
  'fact_observed',
  'state_updated',
  'rule_evaluated',
  'decision_made',
  'snapshot_written'
] as const;

export type EventType = (typeof EVENT_TYPES)[number];
