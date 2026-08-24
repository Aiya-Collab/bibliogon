import { request } from "./http";
export type DistillationProvider = "ollama" | "cloudmist" | "deepseek" | "minimax" | "dashscope" | "doubao";
export type ArtifactType = "outline" | "character" | "setting" | "plot" | "item" | "lore";
export interface DistillationStartResponse { distillation_run_id: string; status: string; provider_used: string; model_used: string; artifact_count: number; }
export interface DistillationRun { id: string; book_id: string; status: string; provider_used: string; result_counts: Record<string, number>; }
export interface StagingArtifact { id: string; type: ArtifactType; title: string; payload: Record<string, unknown>; status: "candidate" | "adopted" | "rejected"; canonical_id: string | null; }
export const distillationApi = {
  start: (bookId: string, file: File, opts?: { provider?: DistillationProvider; model?: string; signal?: AbortSignal }) => { const form = new FormData(); form.append("file", file); const q = new URLSearchParams(); if (opts?.provider) q.set("distillation_provider", opts.provider); if (opts?.model) q.set("model", opts.model); q.set("async", "true"); return request<DistillationStartResponse>(`/distillation/books/${bookId}/start?${q}`, { method: "POST", body: form, signal: opts?.signal }); },
  getRun: (id: string, signal?: AbortSignal) => request<DistillationRun>(`/distillation/runs/${id}`, { signal }),
  listStaging: (bookId: string, type: ArtifactType = "outline", signal?: AbortSignal) => request<StagingArtifact[]>(`/distillation/books/${bookId}/staging?type=${type}`, { signal }),
  adopt: (id: string, signal?: AbortSignal) => request<{ id: string; status: "adopted"; artifact_type: ArtifactType; canonical_id: string }>(`/distillation/staging/${id}/adopt`, { method: "POST", signal }),
  reject: (id: string, signal?: AbortSignal) => request<{ id: string; status: "rejected" }>(`/distillation/staging/${id}/reject`, { method: "POST", signal }),
};
