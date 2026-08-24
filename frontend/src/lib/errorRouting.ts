export type UIFeedbackKind = "red-toast" | "yellow-toast" | "red-modal" | "form-inline";
export interface ErrorEnvelope { error: { code: string; message: string; hint: string; retryable: boolean; context?: Record<string, unknown>; detail?: string } }
export interface UIFeedback { kind: UIFeedbackKind; retryable: boolean; retryAfterSeconds?: number; actionable?: "switch-provider" | "report-issue" | "check-config" }
const inline = new Set(["unknown_provider", "invalid_model"]);
const yellow = new Set(["provider_timeout", "provider_rate_limited", "provider_upstream_error", "provider_empty_response", "provider_schema_error"]);
export function routeError(e: ErrorEnvelope): UIFeedback { const c = e.error.code; if (inline.has(c)) return { kind: "form-inline", retryable: false }; if (yellow.has(c)) return { kind: "yellow-toast", retryable: true, actionable: "switch-provider" }; if (["provider_auth_error", "internal_error"].includes(c)) return { kind: "red-modal", retryable: false, actionable: "report-issue" }; return { kind: "red-toast", retryable: e.error.retryable, actionable: c === "provider_unavailable" ? "check-config" : undefined }; }
