import { useCallback, useRef, useState } from "react";
import {
    distillationApi,
    type DistillationRun,
    type StagingArtifact,
    type DistillationProvider,
} from "../api/distillation";
import { routeError, type ErrorEnvelope, type UIFeedback } from "../lib/errorRouting";

export function useDistillation(bookId: string) {
    const [state, setState] = useState<
        "idle" | "uploading" | "processing" | "completed" | "failed"
    >("idle");
    const [run, setRun] = useState<DistillationRun>();
    const [staging, setStaging] = useState<StagingArtifact[]>([]);
    const [error, setError] = useState<unknown>();
    const [feedback, setFeedback] = useState<UIFeedback>();
    const controllerRef = useRef<AbortController | undefined>(undefined);
    const abort = useCallback(() => {
        controllerRef.current?.abort();
    }, []);
    const start = useCallback(
        async (
            file: File,
            opts?: { provider?: DistillationProvider; model?: string },
        ) => {
            const controller = new AbortController();
            controllerRef.current = controller;
            setError(undefined);
            setFeedback(undefined);
            setState("uploading");
            try {
                const started = await distillationApi.start(bookId, file, {
                    ...opts,
                    signal: controller.signal,
                });
                setState("processing");
                for (let i = 0; i < 30; i++) {
                    const current = await distillationApi.getRun(
                        started.distillation_run_id,
                        controller.signal,
                    );
                    setRun(current);
                    if (["succeeded", "failed"].includes(current.status)) {
                        if (current.status === "failed") {
                            throw new Error("distillation failed");
                        }
                        const items = await distillationApi.listStaging(
                            bookId,
                            "outline",
                            controller.signal,
                        );
                        setStaging(items);
                        setState("completed");
                        return current;
                    }
                    await new Promise((r) => setTimeout(r, 2000));
                }
                throw new Error("distillation timeout");
            } catch (e) {
                setError(e);
                const envelope = (e as { detailBody?: unknown })?.detailBody as
                    | ErrorEnvelope
                    | undefined;
                if (envelope?.error) setFeedback(routeError(envelope));
                setState("failed");
                throw e;
            } finally {
                controllerRef.current = undefined;
            }
        },
        [bookId],
    );
    return { state, run, staging, error, feedback, start, abort, setStaging };
}
