import { useCallback, useState } from "react";
import { agentsApi, type AgentBody, type AgentRole } from "../api/agents";
import { routeError, type ErrorEnvelope, type UIFeedback } from "../lib/errorRouting";

function feedbackFor(error: unknown): UIFeedback {
    const envelope = (error as { detailBody?: unknown })?.detailBody as ErrorEnvelope | undefined;
    return envelope?.error ? routeError(envelope) : { kind: "red-toast", retryable: false };
}

export function useAgent<T = unknown>({
    role,
    action,
    body,
    aiRunId,
}: {
    role: AgentRole;
    action: string;
    body: AgentBody;
    aiRunId: string;
}) {
    const [data, setData] = useState<T>();
    const [error, setError] = useState<unknown>();
    const [feedback, setFeedback] = useState<UIFeedback>();
    const [loading, setLoading] = useState(false);
    const run = useCallback(async () => {
        setLoading(true);
        setError(undefined);
        for (let i = 0; i < 4; i++) {
            try {
                const out = await agentsApi.run<T>(role, action, body, aiRunId);
                setData(out);
                return out;
            } catch (e) {
                setError(e);
                const next = feedbackFor(e);
                setFeedback(next);
                if (!next.retryable || i === 3) throw e;
                await new Promise((r) => setTimeout(r, 1000 * 2 ** i));
            } finally {
                setLoading(false);
            }
        }
    }, [role, action, body, aiRunId]);
    return { data, error, feedback, loading, retry: run };
}
