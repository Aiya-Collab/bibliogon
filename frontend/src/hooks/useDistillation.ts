import { useCallback, useRef, useState } from "react";
import { distillationApi, type DistillationRun, type StagingArtifact, type DistillationProvider } from "../api/distillation";
export function useDistillation(bookId: string) {
  const [state, setState] = useState<"idle" | "uploading" | "processing" | "completed" | "failed">("idle");
  const [run, setRun] = useState<DistillationRun>(); const [staging, setStaging] = useState<StagingArtifact[]>([]); const [error, setError] = useState<unknown>(); const abortRef = useRef(false);
  const abort = useCallback(() => { abortRef.current = true; }, []);
  const start = useCallback(async (file: File, opts?: { provider?: DistillationProvider; model?: string }) => { abortRef.current = false; setError(undefined); setState("uploading"); try { const started = await distillationApi.start(bookId, file, opts); setState("processing"); for (let i=0;i<30;i++) { if (abortRef.current) throw new DOMException("Aborted", "AbortError"); const current = await distillationApi.getRun(started.distillation_run_id); setRun(current); if (["succeeded", "failed"].includes(current.status)) { if (current.status === "failed") throw new Error("distillation failed"); const items = await distillationApi.listStaging(bookId); setStaging(items); setState("completed"); return current; } await new Promise(r => setTimeout(r, 2000)); } throw new Error("distillation timeout"); } catch (e) { setError(e); setState("failed"); throw e; } }, [bookId]);
  return { state, run, staging, error, start, abort, setStaging };
}
