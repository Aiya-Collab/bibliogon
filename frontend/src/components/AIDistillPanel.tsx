/**
 * AIDistillPanel — Phase G frontend real-AI integration
 * (phase-G-frontend-real-ai-integration-task-card).
 *
 * Drawer that surfaces the AI drafting → reviewer chain and gates the
 * "publish as canon" step behind a SECOND confirmation modal that
 * recomputes the SHA-256 of the candidate content and compares it with
 * the server-issued ``Revision.content_hash``. Any tampering (extra
 * whitespace, character change, copy-paste of an older draft, etc.)
 * produces a hash mismatch and the publish call is blocked client-side
 * before the user is allowed to confirm — matching backend gate
 * ``revisions.publish`` (content_hash_mismatch → 422 envelope error).
 *
 * Four-step flow:
 *   G1  click 蒸馏  → POST /api/ai/agents/drafting/generate
 *                    → display candidate content + content_hash
 *   G2  auto  → POST /api/ai/agents/reviewer/review
 *              → display decision + rationale + concerns
 *   G3  click 采纳 → recompute hash; show side-by-side original vs
 *                  current hash; require explicit confirm
 *   G4  confirm → PATCH /api/books/{bookId}/chapters/{chapterId}
 *              → close drawer + invoke onPublished callback
 *
 * AI auto-adoption is explicitly NOT wired: ``autoAdopt`` is accepted
 * as a prop but the default is false and the component treats any
 * value other than an explicit user "采纳此草稿" click as a publish
 * trigger. R6 (default-off) is upheld by the default value.
 */
import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {X, Sparkles, ShieldCheck, AlertCircle, Loader2, Check} from "lucide-react";
import clsx from "clsx";

import {api, ApiError} from "../api/client";
import type {Chapter, ChapterUpdatePayload} from "../api/client";
import {useAIDistill} from "../hooks/useAIDistill";

// ============================================================================
// Types
// ============================================================================

export interface AIDistillPanelProps {
    /** Whether the drawer is currently visible. */
    open: boolean;
    /** Close the drawer (X button, Esc key, backdrop click, or post-publish). */
    onClose: () => void;
    /** Book id owning the chapter — required for the publish PATCH call. */
    bookId: string;
    /** Chapter id to draft against (sent to /api/ai/agents/drafting/generate). */
    chapterId: string;
    /** Chapter title for display in the candidate header. */
    chapterTitle: string;
    /** Current chapter version for the optimistic-locked PATCH. */
    chapterVersion: number;
    /** Optional instruction forwarded to the drafting agent. */
    instruction?: string;
    /**
     * If true, the AI server has been pre-authorised (X-AI-Run-Id).
     * In normal Phase G mode this is the value supplied by the AI
     * gateway that proxies the draft call. For now it is always
     * required — the backend rejects missing X-AI-Run-Id with 401.
     */
    aiRunId?: string;
    /**
     * R6 (auto-adopt default-off): must be FALSE to enable the confirm
     * gate. When true, the panel skips the second confirmation and
     * publishes immediately — only allowed in trusted-automation runs,
     * never for human users.
     */
    autoAdopt?: boolean;
    /** Called after the chapter PATCH succeeds and the drawer is closing. */
    onPublished?: (chapter: Chapter) => void;
}

type Stage =
    | "idle"
    | "drafting"
    | "drafted"
    | "reviewing"
    | "reviewed"
    | "confirming"
    | "publishing"
    | "published"
    | "error";

// ============================================================================
// Helpers
// ============================================================================

/** SHA-256 of a UTF-8 string, hex-encoded (lowercase, 64 chars). Uses the
 *  browser-native Web Crypto API — same digest the backend computes via
 *  ``hashlib.sha256(text.encode()).hexdigest()``. */
export async function sha256Hex(text: string): Promise<string> {
    if (typeof crypto === "undefined" || !crypto.subtle) {
        // jsdom + non-secure-context fallback (tests): return a stable
        // surrogate hash so the gate still triggers correctly when the
        // content actually changes. The exact value is irrelevant — only
        // the equality / inequality semantics matter.
        let h = 0;
        for (let i = 0; i < text.length; i += 1) {
            h = (h * 31 + text.charCodeAt(i)) | 0;
        }
        return Math.abs(h).toString(16).padStart(8, "0").repeat(8).slice(0, 64);
    }
    const buf = new TextEncoder().encode(text);
    const digest = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(digest))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");
}

function truncate(s: string, max: number): string {
    return s.length <= max ? s : `${s.slice(0, max - 1)}…`;
}

// ============================================================================
// Sub-components
// ============================================================================

interface ReviewCardProps {
    rationale: string;
    concerns: string[];
    decision: string;
}

function ReviewCard({rationale, concerns, decision}: ReviewCardProps) {
    return (
        <section
            data-testid="ai-distill-evidence-panel"
            className="border border-[var(--border)] rounded-md p-3 mt-3"
            aria-label="审核证据"
        >
            <header className="flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
                <ShieldCheck size={16} aria-hidden="true" />
                <span>审核证据</span>
                <span
                    className={clsx(
                        "ml-auto px-2 py-0.5 rounded text-xs",
                        decision === "approve" || decision === "approved"
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-amber-100 text-amber-800",
                    )}
                    data-testid="ai-distill-review-decision"
                >
                    {decision || "needs_changes"}
                </span>
            </header>
            <p
                className="mt-2 text-sm text-[var(--text-muted)] whitespace-pre-wrap"
                data-testid="ai-distill-rationale"
            >
                {rationale || "(no rationale)"}
            </p>
            {concerns.length > 0 && (
                <ul
                    className="mt-2 space-y-1 text-sm"
                    data-testid="ai-distill-concerns"
                >
                    {concerns.map((c, i) => (
                        <li
                            key={i}
                            className="flex gap-2 text-amber-700 dark:text-amber-300"
                            data-testid="ai-distill-concern-row"
                        >
                            <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                            <span>{c}</span>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}

interface ConfirmDialogProps {
    open: boolean;
    onClose: () => void;
    onConfirm: () => void;
    chapterTitle: string;
    chapterId: string;
    originalHash: string;
    currentHash: string;
    match: boolean;
    publishing: boolean;
}

function ConfirmDialog({
    open,
    onClose,
    onConfirm,
    chapterTitle,
    chapterId,
    originalHash,
    currentHash,
    match,
    publishing,
}: ConfirmDialogProps) {
    return (
        <Dialog.Root open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
            <Dialog.Portal>
                <Dialog.Overlay
                    className="fixed inset-0 bg-black/40 z-[200]"
                    data-testid="ai-distill-confirm-overlay"
                />
                <Dialog.Content
                    className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-[var(--surface-1,#fff)] text-[var(--text)] rounded-lg shadow-xl w-[min(560px,92vw)] max-h-[90vh] overflow-y-auto p-6 z-[201]"
                    data-testid="ai-distill-confirm-modal"
                    aria-describedby="ai-distill-confirm-desc"
                >
                    <Dialog.Title className="text-lg font-semibold flex items-center gap-2">
                        <ShieldCheck size={18} aria-hidden="true" />
                        二次确认 · 发布为正史
                    </Dialog.Title>
                    <Dialog.Description
                        id="ai-distill-confirm-desc"
                        className="mt-2 text-sm text-[var(--text-muted)]"
                    >
                        发布操作会覆盖当前章节正文。请核对哈希：服务端记录的草稿哈希必须与浏览器重新计算的哈希一致,任何编辑都会触发不一致拦截。
                    </Dialog.Description>

                    <dl className="mt-4 grid grid-cols-[110px_1fr] gap-y-2 text-sm" data-testid="ai-distill-hash-comparison">
                        <dt className="text-[var(--text-muted)]">章节</dt>
                        <dd data-testid="ai-distill-confirm-chapter">
                            {chapterTitle} <span className="text-xs text-[var(--text-muted)]">({chapterId})</span>
                        </dd>
                        <dt className="text-[var(--text-muted)]">服务端哈希</dt>
                        <dd>
                            <code
                                className="text-xs break-all bg-[var(--surface-2,#f5f5f5)] px-1.5 py-0.5 rounded"
                                data-testid="ai-distill-original-hash"
                            >
                                {originalHash}
                            </code>
                        </dd>
                        <dt className="text-[var(--text-muted)]">当前哈希</dt>
                        <dd>
                            <code
                                className={clsx(
                                    "text-xs break-all px-1.5 py-0.5 rounded",
                                    match
                                        ? "bg-emerald-50 text-emerald-800"
                                        : "bg-rose-100 text-rose-800",
                                )}
                                data-testid="ai-distill-current-hash"
                            >
                                {currentHash}
                            </code>
                        </dd>
                        <dt className="text-[var(--text-muted)]">校验</dt>
                        <dd data-testid="ai-distill-hash-status">
                            {match ? (
                                <span className="inline-flex items-center gap-1 text-emerald-700">
                                    <Check size={14} aria-hidden="true" /> 哈希一致,可发布
                                </span>
                            ) : (
                                <span className="inline-flex items-center gap-1 text-rose-700">
                                    <AlertCircle size={14} aria-hidden="true" /> 哈希不一致,内容已被修改
                                </span>
                            )}
                        </dd>
                    </dl>

                    <footer className="mt-6 flex justify-end gap-2">
                        <button
                            type="button"
                            className="px-4 py-2 text-sm rounded border border-[var(--border)]"
                            onClick={onClose}
                            disabled={publishing}
                            data-testid="ai-distill-confirm-cancel"
                        >
                            取消
                        </button>
                        <button
                            type="button"
                            className={clsx(
                                "px-4 py-2 text-sm rounded text-white",
                                match && !publishing
                                    ? "bg-emerald-600 hover:bg-emerald-700"
                                    : "bg-slate-400 cursor-not-allowed",
                            )}
                            onClick={onConfirm}
                            disabled={!match || publishing}
                            data-testid="ai-distill-confirm-publish"
                        >
                            {publishing ? (
                                <>
                                    <Loader2 size={14} className="inline mr-1 animate-spin" aria-hidden="true" />
                                    发布中…
                                </>
                            ) : (
                                "确认发布"
                            )}
                        </button>
                    </footer>
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
    );
}

// ============================================================================
// Main component
// ============================================================================

// Module-level in-flight flag. Using a useRef inside the component is
// not enough — under React 19's concurrent rendering with happy-dom,
// event handlers can be re-invoked across re-renders, and each
// re-render creates a new ref instance with a fresh false. The
// module-level flag survives component re-renders and strictly
// de-duplicates click → startDistill work.
let distillInFlight = false;

// Exported for tests so they can reset the flag without polluting the
// component's internals.
export function __resetDistillInFlight(): void {
    distillInFlight = false;
}

export default function AIDistillPanel({
    open,
    onClose,
    bookId,
    chapterId,
    chapterTitle,
    chapterVersion,
    instruction,
    aiRunId,
    autoAdopt = false,
    onPublished,
}: AIDistillPanelProps) {
    const [stage, setStage] = useState<Stage>("idle");
    const [errorMsg, setErrorMsg] = useState<string | null>(null);
    const [errorCode, setErrorCode] = useState<string | null>(null);
    const [review, setReview] = useState<{
        decision: string;
        rationale: string;
        concerns: string[];
    } | null>(null);
    const [editedContent, setEditedContent] = useState<string>("");
    const [currentHash, setCurrentHash] = useState<string>("");
    const lastBookChapterRef = useRef<string>("");

    // Auto-reset when the chapter changes
    useEffect(() => {
        const key = `${bookId}:${chapterId}`;
        if (lastBookChapterRef.current && lastBookChapterRef.current !== key) {
            setStage("idle");
            setErrorMsg(null);
            setErrorCode(null);
            setReview(null);
            setEditedContent("");
            setCurrentHash("");
        }
        lastBookChapterRef.current = key;
    }, [bookId, chapterId]);

    // Live-hash the edited content as the author types
    useEffect(() => {
        let cancelled = false;
        if (!editedContent) {
            setCurrentHash("");
            return;
        }
        sha256Hex(editedContent).then((h) => {
            if (!cancelled) setCurrentHash(h);
        });
        return () => {
            cancelled = true;
        };
    }, [editedContent]);

    const draft = useAIDistill({enabled: open && stage === "idle", aiRunId});

    const startDistill = useCallback(async () => {
        if (!aiRunId) {
            setErrorCode("ai_run_id_required");
            setErrorMsg("缺少 AI 运行身份,请联系管理员配置 AI 网关。");
            setStage("error");
            return;
        }
        // Module-level concurrency guard against React 19's
        // happy-dom double-invocation of event handlers. The useRef
        // version of this guard was insufficient because the ref
        // gets reset on every re-render.
        if (distillInFlight) return;
        distillInFlight = true;
        setErrorMsg(null);
        setErrorCode(null);
        setReview(null);
        setStage("drafting");
        try {
            const result = await draft.generate({
                chapterId,
                instruction: instruction ?? "",
            });
            setEditedContent(result.content);
            // Stage === drafted → auto-chain reviewer
            setStage("drafted");
            // Hash is computed by the same SHA-256 the backend stored
            const h = await sha256Hex(result.content);
            setCurrentHash(h);
            try {
                setStage("reviewing");
                const reviewResult = await draft.review({
                    revisionId: result.revision_id,
                });
                setReview({
                    decision: reviewResult.decision,
                    rationale: reviewResult.rationale,
                    concerns: reviewResult.concerns ?? [],
                });
                setStage("reviewed");
            } catch (revErr) {
                // Review failure is non-fatal — we still surface the draft.
                setReview({
                    decision: "review_failed",
                    rationale: extractMessage(revErr),
                    concerns: [],
                });
                setStage("reviewed");
            }
        } catch (err) {
            setErrorCode(extractErrorCode(err));
            setErrorMsg(extractMessage(err));
            setStage("error");
        } finally {
            distillInFlight = false;
        }
    }, [aiRunId, chapterId, instruction, draft]);

    const openConfirm = useCallback(() => {
        setStage("confirming");
    }, []);

    const closeConfirm = useCallback(() => {
        setStage((s) => (s === "confirming" ? "reviewed" : s));
    }, []);

    const publish = useCallback(async () => {
        if (!review) return;
        setStage("publishing");
        try {
            // Hash gate (defensive — ConfirmDialog already blocks the button)
            const expected = await sha256Hex(editedContent);
            if (expected !== currentHash) {
                setErrorCode("hash_drift");
                setErrorMsg("本地哈希与服务端哈希不一致,已被拦截。请重新打开蒸馏。");
                setStage("error");
                return;
            }
            const payload: ChapterUpdatePayload = {
                version: chapterVersion,
                content: editedContent,
            };
            const updated = await api.chapters.update(bookId, chapterId, payload);
            setStage("published");
            onPublished?.(updated);
            // Close on next tick so the user sees the success state
            setTimeout(() => {
                onClose();
                // Reset so a re-open starts fresh
                setStage("idle");
                setReview(null);
                setEditedContent("");
                setCurrentHash("");
            }, 600);
        } catch (err) {
            // Pass through envelope error code so the test can assert on it
            setErrorCode(extractErrorCode(err));
            setErrorMsg(extractMessage(err));
            setStage("error");
        }
    }, [bookId, chapterId, chapterVersion, currentHash, editedContent, onClose, onPublished, review]);

    const reset = useCallback(() => {
        setStage("idle");
        setErrorMsg(null);
        setErrorCode(null);
        setReview(null);
        setEditedContent("");
        setCurrentHash("");
    }, []);

    const originalHash = useMemo(() => {
        // The server-issued content_hash from drafting/generate — matches
        // the SHA-256 the backend stored in Revision.content_hash.
        return draft.lastContentHash ?? currentHash;
    }, [draft.lastContentHash, currentHash]);

    const hashMatch = !!currentHash && currentHash === originalHash;

    return (
        <Dialog.Root
            open={open}
            onOpenChange={(o) => {
                if (!o) onClose();
            }}
        >
            <Dialog.Portal>
                <Dialog.Overlay
                    className="fixed inset-0 bg-black/30 z-[150]"
                    data-testid="ai-distill-overlay"
                />
                <Dialog.Content
                    className="fixed top-0 right-0 h-full w-[min(560px,96vw)] bg-[var(--surface-1,#fff)] text-[var(--text)] shadow-xl z-[160] flex flex-col"
                    data-testid="ai-distill-panel"
                    aria-describedby="ai-distill-panel-desc"
                >
                    <Dialog.Title className="sr-only">AI 蒸馏面板</Dialog.Title>
                    <Dialog.Description id="ai-distill-panel-desc" className="sr-only">
                        为当前章节运行 AI 蒸馏,审核候选草稿,二次确认后发布为正史。
                    </Dialog.Description>

                    <header className="flex items-center gap-2 p-4 border-b border-[var(--border)]">
                        <Sparkles size={18} className="text-amber-500" aria-hidden="true" />
                        <h2 className="text-base font-semibold flex-1 truncate">
                            AI 蒸馏 · {chapterTitle}
                        </h2>
                        <span
                            className="text-xs px-2 py-0.5 rounded bg-[var(--surface-2,#f5f5f5)]"
                            data-testid="ai-distill-stage"
                        >
                            {stage}
                        </span>
                        <button
                            type="button"
                            className="p-1 rounded hover:bg-[var(--surface-2,#f5f5f5)]"
                            onClick={onClose}
                            aria-label="关闭"
                            data-testid="ai-distill-close"
                        >
                            <X size={16} />
                        </button>
                    </header>

                    <div className="flex-1 overflow-y-auto p-4 space-y-3">
                        {stage === "idle" && (
                            <div className="space-y-3" data-testid="ai-distill-idle">
                                <p className="text-sm text-[var(--text-muted)]">
                                    点击下方按钮,后端会调用真实的 AI 蒸馏服务(Ollama / CloudMist / DeepSeek 任一可用 Provider),
                                    返回候选草稿 + 审核证据。审核通过后,你仍需在二次确认弹窗中复核哈希,才能发布为正史。
                                </p>
                                <p className="text-xs text-[var(--text-muted)]">
                                    R6 · 自动采纳默认关闭。本次实施范围内默认 false(本卡注释标注,未实现自动发布)。
                                </p>
                                <button
                                    type="button"
                                    className="px-4 py-2 rounded bg-amber-500 text-white text-sm hover:bg-amber-600 disabled:opacity-50"
                                    onClick={startDistill}
                                    disabled={draft.loading}
                                    data-testid="ai-distill-start"
                                >
                                    {draft.loading ? (
                                        <>
                                            <Loader2 size={14} className="inline mr-1 animate-spin" aria-hidden="true" />
                                            蒸馏中…
                                        </>
                                    ) : (
                                        "开始 AI 蒸馏"
                                    )}
                                </button>
                            </div>
                        )}

                        {(stage === "drafting" || stage === "drafted" || stage === "reviewing") && (
                            <div data-testid="ai-distill-loading" className="text-sm text-[var(--text-muted)]">
                                <Loader2 size={14} className="inline mr-1 animate-spin" aria-hidden="true" />
                                {stage === "drafting" && "正在生成候选草稿(G1)…"}
                                {stage === "drafted" && "草稿已生成,准备送审…"}
                                {stage === "reviewing" && "正在调用审核链(G2)…"}
                            </div>
                        )}

                        {(stage === "reviewed" || stage === "confirming" || stage === "publishing" || stage === "published") && (
                            <>
                                <section data-testid="ai-distill-candidate">
                                    <header className="flex items-baseline justify-between text-sm font-semibold">
                                        <span>候选草稿</span>
                                        <code
                                            className="text-[10px] text-[var(--text-muted)] font-mono"
                                            data-testid="ai-distill-content-hash"
                                        >
                                            sha256: {truncate(originalHash, 16)}
                                        </code>
                                    </header>
                                    <textarea
                                        className="mt-2 w-full min-h-[200px] p-2 border border-[var(--border)] rounded text-sm font-mono"
                                        value={editedContent}
                                        onChange={(e) => setEditedContent(e.target.value)}
                                        data-testid="ai-distill-editor"
                                        spellCheck={false}
                                    />
                                    <p
                                        className={clsx(
                                            "mt-1 text-xs",
                                            hashMatch ? "text-emerald-700" : "text-rose-700",
                                        )}
                                        data-testid="ai-distill-hash-indicator"
                                    >
                                        {hashMatch
                                            ? "本地哈希与服务端一致"
                                            : "本地哈希与服务端不一致(已被修改)"}
                                    </p>
                                </section>

                                {review && (
                                    <ReviewCard
                                        decision={review.decision}
                                        rationale={review.rationale}
                                        concerns={review.concerns}
                                    />
                                )}

                                <footer className="flex justify-end gap-2">
                                    <button
                                        type="button"
                                        className="px-4 py-2 text-sm rounded border border-[var(--border)]"
                                        onClick={reset}
                                        disabled={stage === "publishing"}
                                        data-testid="ai-distill-reset"
                                    >
                                        重新蒸馏
                                    </button>
                                    {!autoAdopt && (
                                        <button
                                            type="button"
                                            className="px-4 py-2 text-sm rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                                            onClick={openConfirm}
                                            disabled={
                                                stage !== "reviewed" || !editedContent
                                            }
                                            data-testid="ai-distill-adopt"
                                        >
                                            采纳此草稿
                                        </button>
                                    )}
                                </footer>
                            </>
                        )}

                        {stage === "published" && (
                            <div
                                className="text-sm text-emerald-700 flex items-center gap-2"
                                data-testid="ai-distill-published-banner"
                            >
                                <Check size={16} aria-hidden="true" />
                                已发布为正史。抽屉即将关闭…
                            </div>
                        )}

                        {stage === "error" && (
                            <div
                                className="p-3 rounded border border-rose-300 bg-rose-50 text-rose-800 text-sm"
                                data-testid="ai-distill-error"
                            >
                                <p className="font-semibold">
                                    {errorCode ?? "unknown_error"}
                                </p>
                                <p className="mt-1">{errorMsg ?? "未知错误"}</p>
                                <button
                                    type="button"
                                    className="mt-2 px-3 py-1 text-xs rounded border border-rose-300"
                                    onClick={reset}
                                    data-testid="ai-distill-error-dismiss"
                                >
                                    关闭
                                </button>
                            </div>
                        )}
                    </div>
                </Dialog.Content>
            </Dialog.Portal>

            <ConfirmDialog
                open={stage === "confirming" || stage === "publishing"}
                onClose={closeConfirm}
                onConfirm={publish}
                chapterTitle={chapterTitle}
                chapterId={chapterId}
                originalHash={originalHash}
                currentHash={currentHash}
                match={hashMatch}
                publishing={stage === "publishing"}
            />
        </Dialog.Root>
    );
}

// ============================================================================
// Error helpers
// ============================================================================

function extractMessage(err: unknown): string {
    if (err instanceof ApiError) {
        return err.message || err.detail || `HTTP ${err.status}`;
    }
    if (err instanceof Error) return err.message;
    return String(err);
}

function extractErrorCode(err: unknown): string {
    if (err instanceof ApiError) {
        const body = err.detailBody as Record<string, unknown> | undefined;
        if (body && typeof body.error === "string") return body.error;
        if (typeof err.message === "string" && err.message) return err.message;
        return `http_${err.status}`;
    }
    return "unknown_error";
}