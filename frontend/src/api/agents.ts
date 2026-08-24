import { request } from "./http";
export type AgentRole = "drafting" | "reviewer" | "scribe" | "foreshadow" | "worldbuilder" | "outliner" | "context";
export interface AgentBody { chapter_id?: string; book_id?: string; revision_id?: string; instruction?: string; context_refs?: string[]; scope?: string; }
export interface AgentRun { id: string; agent_role: AgentRole; status: "success" | "failed"; provider_name: string; model_name: string; created_at: string; }
export const agentsApi = { run: <T = unknown>(role: AgentRole, action: string, body: AgentBody, aiRunId: string) => request<T>(`/ai/agents/${role}/${action}`, { method: "POST", body: JSON.stringify(body), headers: { "X-AI-Run-Id": aiRunId } }), listRuns: () => request<AgentRun[]>("/ai/agents/runs") };
