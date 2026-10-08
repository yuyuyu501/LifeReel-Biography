export type ProfileValue = string | Record<string, unknown> | unknown[];
export type ProfileState =
  "empty" | "filled" | "unknown" | "deferred" | "declined" | "not_applicable";
export type ProfileCertainty =
  "reported" | "confirmed" | "uncertain" | "disputed" | "pending";
export type ProfileUse = "works" | "internal" | "pseudonym";
export interface ProfileField {
  key: string;
  label: string;
  kind: string;
  priority: string;
  question: string;
  section: string;
}
export interface ProfileEntry {
  id: string;
  field_key: string;
  record_key: string;
  value: ProfileValue;
  state: ProfileState;
  certainty: ProfileCertainty;
  use_scope: ProfileUse;
  source: {
    type: string;
    id?: string;
    version?: number;
    quote?: string;
    actor?: string;
  };
  version_number: number;
  pseudonyms?: Record<string, string>;
}
export interface LifeReadiness {
  status: "not_ready" | "partial_ready" | "ready";
  profile_version: number;
  rule_version: string;
  scope: ProfileValue;
  processed_fields: number;
  total_fields: number;
  usable_entries: number;
  message: string;
  themes: {
    title: string;
    section: string;
    entry_ids: string[];
    reason: string;
  }[];
  missing_fields: {
    key: string;
    label: string;
    question: string;
    section: string;
  }[];
}
export interface LifeProfile {
  id: string;
  subject_id: string;
  template_version: string;
  version_number: number;
  sections: { key: string; title: string }[];
  fields: ProfileField[];
  entries: ProfileEntry[];
  readiness: LifeReadiness;
}
export interface ProfileChange {
  id?: string;
  field_key: string;
  record_key: string;
  value: ProfileValue;
  state: ProfileState;
  certainty: ProfileCertainty;
  use_scope: ProfileUse;
  delete?: boolean;
  pseudonyms?: Record<string, string>;
}
