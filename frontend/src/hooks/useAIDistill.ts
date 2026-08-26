/**
 * useAIDistill — Phase G frontend real-AI integration
 * (phase-G-frontend-real-ai-integration-task-card).
 *
 * Thin wrapper around the existing `agentsApi` that exposes the two
 * endpoints the panel needs:
 *
 *   - drafting/generate  → returns { revision_id, content, content_hash, status }
 *   - reviewer/review    → returns { decision, rationale, suggested_hash, concerns }
 *
 * The hook exposes the raw last success payloads via `lastContent` and
 * `lastContentHash` so the panel can render the candidate without
 * juggling async state itself. Errors are surfaced via the standard
 * `ApiError` envelope (status, message, detailBody with error code),
 * which the panel reads to display envelope error codes verbatim —
 * matching the backend contract patched in 005.
 *
 * The hook does NOT do any optimistic-locking or PATCH work; that
 * lives in AIDistillPanel.publish() so the hash gate and the chapter
 * version are computed from a single source of truth (the panel's
 * edited draft).
 */
import {useCallback, useState} from "react";

import {agentsApi, type AgentBody} from "../api/agents";

export interface UseAIDistillParams {
    /** When false, generate() and review() short-circuit without firing. */
    enabled?: boolean;
    /**
     * X-AI-Run-Id — required by the backend's `require_ai_identity`
     * dependency. Without it, every call returns 401. In Phase G this
     * is supplied by the AI gateway / desktop runtime that brokers the
     * call. For unit tests a fake id like "test-run-1" is acceptable
     * because tests mock the network layer.
     */
    aiRunId?: string;
}

export interface DraftingResult {
    revision_id: string;
    content: string;
    content_hash: string;
    status: string;
}

export interface ReviewResult {
    decision: string;
    rationale: string;
    suggested_hash: string;
    concerns: string[];
}

export interface UseAIDistillReturn {
    loading: boolean;
    error: unknown;
    /** Latest successful drafting result (or null until first generate). */
    lastContent: string | null;
    /** Convenience accessor — same as `lastContent ? sha256Hex(lastContent) : null`. */
    lastContentHash: string | null;
    /** Latest successful review result. */
    lastReview: ReviewResult | null;
    /** G1 — call /api/ai/agents/drafting/generate. */
    generate: (params: {chapterId: string; instruction?: string}) => Promise<DraftingResult>;
    /** G2 — call /api/ai/agents/reviewer/review. */
    review: (params: {revisionId: string}) => Promise<ReviewResult>;
}

export function useAIDistill(params: UseAIDistillParams = {}): UseAIDistillReturn {
    const {enabled = true, aiRunId} = params;
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<unknown>(null);
    const [lastContent, setLastContent] = useState<string | null>(null);
    const [lastContentHash, setLastContentHash] = useState<string | null>(null);
    const [lastReview, setLastReview] = useState<ReviewResult | null>(null);

    const generate = useCallback(
        async ({chapterId, instruction}: {chapterId: string; instruction?: string}): Promise<DraftingResult> => {
            if (!enabled) throw new Error("disabled");
            if (!aiRunId) throw new Error("ai_run_id_required");
            setLoading(true);
            setError(null);
            try {
                const body: AgentBody = {chapter_id: chapterId, instruction};
                const result = await agentsApi.run<DraftingResult>(
                    "drafting",
                    "generate",
                    body,
                    aiRunId,
                );
                setLastContent(result.content);
                setLastContentHash(result.content_hash);
                return result;
            } catch (err) {
                setError(err);
                throw err;
            } finally {
                setLoading(false);
            }
        },
        [aiRunId, enabled],
    );

    const review = useCallback(
        async ({revisionId}: {revisionId: string}): Promise<ReviewResult> => {
            if (!enabled) throw new Error("disabled");
            if (!aiRunId) throw new Error("ai_run_id_required");
            setLoading(true);
            setError(null);
            try {
                const body: AgentBody = {revision_id: revisionId};
                const result = await agentsApi.run<ReviewResult>(
                    "reviewer",
                    "review",
                    body,
                    aiRunId,
                );
                setLastReview(result);
                return result;
            } catch (err) {
                setError(err);
                throw err;
            } finally {
                setLoading(false);
            }
        },
        [aiRunId, enabled],
    );

    return {loading, error, lastContent, lastContentHash, lastReview, generate, review};
}