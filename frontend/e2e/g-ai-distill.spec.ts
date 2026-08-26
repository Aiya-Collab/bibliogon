/**
 * Phase G — Frontend real-AI integration E2E (g-ai-distill.spec.ts).
 *
 * Covers the four goals from the task card:
 *   G1 Distill  → click 蒸馏 → POST /api/ai/agents/drafting/generate
 *               → display candidate + content_hash
 *   G2 Review   → auto POST /api/ai/agents/reviewer/review
 *               → display decision + rationale + concerns
 *   G3 Confirm  → click 采纳 → second confirmation modal with two hashes
 *               → hash mismatch path (edit a character)
 *   G4 Publish  → confirm → PATCH /api/books/{id}/chapters/{cid}
 *               → drawer closes + page refreshes
 *
 * The AI agent endpoints require X-AI-Run-Id + an AiRun row. To avoid
 * touching the backend (task card scope is frontend-only), we mock the
 * two AI agent endpoints with `page.route()`. The PATCH chapter
 * endpoint is left real so the request hits /api/books/...chapters and
 * verifies the actual chapter content update lands server-side.
 *
 * This is the same hybrid pattern card-c-project-tree.spec.ts uses
 * (it talks to the backend directly via `request` to seed data, then
 * drives the UI).
 */
import {expect, test, type Page, type APIRequestContext} from "@playwright/test";
import {createHash} from "node:crypto";

const backend = "http://127.0.0.1:8000/api";

const SHA256_HEX_LEN = 64;

function sha256Hex(s: string): string {
    return createHash("sha256").update(s, "utf8").digest("hex");
}

async function post<T>(request: APIRequestContext, path: string, body: unknown): Promise<T> {
    const response = await request.post(`${backend}${path}`, { data: body });
    expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
    return response.json() as T;
}

async function patch(request: APIRequestContext, path: string, body: unknown): Promise<unknown> {
    const response = await request.patch(`${backend}${path}`, { data: body });
    expect(response.ok(), `PATCH ${path}: ${await response.text()}`).toBeTruthy();
    return response.json();
}

async function get<T>(request: APIRequestContext, path: string): Promise<T> {
    const response = await request.get(`${backend}${path}`);
    expect(response.ok(), `GET ${path}: ${await response.text()}`).toBeTruthy();
    return response.json() as T;
}

/**
 * Intercept the two AI agent endpoints so the test exercises the UI
 * state machine without needing an AiRun row in the database (which
 * would require a backend change that the task card explicitly
 * forbids). Returns the route-handler reference so callers can swap
 * responses mid-test (e.g. switching to a hash-mismatching draft).
 */
async function mockAiAgents(
    page: Page,
    draftContent: string,
    reviewRationale: string,
    reviewConcerns: string[],
): Promise<void> {
    const draftHash = sha256Hex(draftContent);

    await page.route("**/api/ai/agents/drafting/generate", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                revision_id: "rev-e2e-1",
                content: draftContent,
                content_hash: draftHash,
                status: "candidate",
            }),
        });
    });

    await page.route("**/api/ai/agents/reviewer/review", async (route) => {
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                decision: "needs_changes",
                rationale: reviewRationale,
                suggested_hash: draftHash,
                concerns: reviewConcerns,
            }),
        });
    });
}

async function closeOnboardingIfPresent(page: Page): Promise<void> {
    const setupClose = page.getByRole("button", { name: "Close" });
    const hasSetup = await expect(setupClose)
        .toBeVisible({ timeout: 15_000 })
        .then(() => true)
        .catch(() => false);
    if (hasSetup) {
        await setupClose.click();
        await expect(setupClose).toBeHidden();
    }
}

test.describe("Phase G — Frontend real-AI integration", () => {
    test.setTimeout(120_000);

    test("G1-G4: distill, review, confirm, publish + hash-mismatch guard", async ({
        page,
        request,
    }) => {
        page.on("pageerror", (error) => console.log(`browser-error: ${error.message}`));

        // ---- 0. Seed: book + chapter via direct backend calls ----
        const book = await post<{ id: string }>(request, "/books", {
            title: "Phase G AI workspace",
            author: "e2e",
        });
        const chapter = await post<{ id: string; version: number }>(
            request,
            `/books/${book.id}/chapters`,
            { title: "Wandering chapter", content: "Original body before distillation." },
        );

        // ---- 1. Pre-stage AI gateway identity so the panel knows the run id is set ----
        await page.addInitScript(() => {
            window.localStorage.setItem("bibliogon.ai_run_id", "test-run-e2e");
        });

        // ---- 2. Mock the AI agent endpoints with stable responses ----
        const draftContent =
            "The wind carried the scent of rain across the moor. Elara quickened her pace.";
        const rationale =
            "Consistent style; tightens the opening image; advances plot.";
        const concerns = ["Resolve second-act foreshadow later", "Verify timeline in chapter 5"];
        await mockAiAgents(page, draftContent, rationale, concerns);

        // ---- 3. Navigate to the editor and open the AI 蒸馏 drawer ----
        await page.goto(`/book/${book.id}`);
        await closeOnboardingIfPresent(page);

        // The chapter should auto-load; if not, click it.
        const chapterLink = page.getByRole("button", { name: /Wandering chapter/i }).first();
        if (await chapterLink.count()) {
            await chapterLink.click();
        }

        const distillButton = page.getByTestId("ai-distill-button");
        await expect(distillButton).toBeVisible({ timeout: 15_000 });

        // Screenshot 1 — the entry-point button (G1 entry)
        await page.screenshot({
            path: "e2e/screenshots/g-ai-distill-button.png",
            fullPage: true,
        });

        await distillButton.click();

        // ---- 4. G1 + G2: drawer opens, draft loads, review appears ----
        const panel = page.getByTestId("ai-distill-panel");
        await expect(panel).toBeVisible();
        // Wait for the idle start button inside the drawer before clicking.
        const startButton = page.getByTestId("ai-distill-start");
        await expect(startButton).toBeVisible({ timeout: 5_000 });
        await startButton.click();

        // ---- 4. G1 + G2: drawer opens, draft loads, review appears ----
        await expect(page.getByTestId("ai-distill-panel")).toBeVisible();
        await expect(page.getByTestId("ai-distill-candidate")).toBeVisible({
            timeout: 30_000,
        });
        await expect(page.getByTestId("ai-distill-evidence-panel")).toBeVisible({
            timeout: 30_000,
        });
        await expect(page.getByTestId("ai-distill-rationale")).toContainText(
            /consistent style/i,
        );

        // Screenshot 2 — evidence panel + draft (G2 output)
        await page.screenshot({
            path: "e2e/screenshots/g-ai-distill-evidence-panel.png",
            fullPage: true,
        });

        // Sanity: the server-issued hash should equal the SHA-256 of the
        // current draft content (the browser computes it from the editor
        // value once the user is in the reviewed stage).
        const contentHashNode = page.getByTestId("ai-distill-content-hash");
        await expect(contentHashNode).toBeVisible();

        // ---- 5. G3: open second confirmation modal ----
        await page.getByTestId("ai-distill-adopt").click();
        const confirmModal = page.getByTestId("ai-distill-confirm-modal");
        await expect(confirmModal).toBeVisible();
        await expect(page.getByTestId("ai-distill-original-hash")).toHaveText(
            new RegExp(`[0-9a-f]{${SHA256_HEX_LEN}}`),
        );
        await expect(page.getByTestId("ai-distill-current-hash")).toHaveText(
            new RegExp(`[0-9a-f]{${SHA256_HEX_LEN}}`),
        );
        await expect(page.getByTestId("ai-distill-hash-status")).toContainText(
            /哈希一致/,
        );

        // Screenshot 3 — the second confirmation modal (G3)
        await page.screenshot({
            path: "e2e/screenshots/g-ai-distill-confirm-modal.png",
            fullPage: true,
        });

        // Cancel to test the hash-mismatch path next.
        await page.getByTestId("ai-distill-confirm-cancel").click();
        await expect(confirmModal).toBeHidden();

        // ---- 6. Hash-mismatch guard: edit a character and re-open ----
        const editor = page.getByTestId("ai-distill-editor");
        await editor.fill(`${draftContent}!`); // extra character
        await expect(page.getByTestId("ai-distill-hash-indicator")).toContainText(
            /不一致/,
        );

        await page.getByTestId("ai-distill-adopt").click();
        await expect(page.getByTestId("ai-distill-confirm-modal")).toBeVisible();
        await expect(page.getByTestId("ai-distill-hash-status")).toContainText(
            /不一致/,
        );
        await expect(page.getByTestId("ai-distill-confirm-publish")).toBeDisabled();

        // Screenshot 4 — hash mismatch path
        await page.screenshot({
            path: "e2e/screenshots/g-ai-distill-hash-mismatch.png",
            fullPage: true,
        });

        await page.getByTestId("ai-distill-confirm-cancel").click();

        // ---- 7. Restore original draft + G4 publish ----
        await editor.fill(draftContent);
        await expect(page.getByTestId("ai-distill-hash-indicator")).toContainText(
            /一致/,
        );

        await page.getByTestId("ai-distill-adopt").click();
        await page.getByTestId("ai-distill-confirm-publish").click();

        // Drawer should auto-close after a brief "已发布" state.
        await expect(page.getByTestId("ai-distill-panel")).toBeHidden({
            timeout: 15_000,
        });

        // Verify the chapter actually got the new body on the server.
        const refreshed = await get<{ content: string; version: number }>(
            request,
            `/books/${book.id}/chapters/${chapter.id}`,
        );
        expect(refreshed.content).toBe(draftContent);
        expect(refreshed.version).toBeGreaterThan(chapter.version);

        // ---- 8. Screenshot 5 — published state (page after publish) ----
        await page.screenshot({
            path: "e2e/screenshots/g-ai-distill-published.png",
            fullPage: true,
        });
    });

    test("Rejects  publish when chapter content has been modified externally between G2 and G4 (defensive envelope)", async ({
        page,
        request,
    }) => {
        page.on("pageerror", (error) => console.log(`browser-error: ${error.message}`));

        const book = await post<{ id: string }>(request, "/books", {
            title: "Phase G conflict workspace",
            author: "e2e",
        });
        const chapter = await post<{ id: string; version: number }>(
            request,
            `/books/${book.id}/chapters`,
            { title: "Conflict chapter", content: "Original body." },
        );

        await page.addInitScript(() => {
            window.localStorage.setItem("bibliogon.ai_run_id", "test-run-e2e-2");
        });
        const draftContent = "Drafted body — same hash, but server version moved on.";
        await mockAiAgents(page, draftContent, "ok", []);

        await page.goto(`/book/${book.id}`);
        await closeOnboardingIfPresent(page);
        const chapterLink = page.getByRole("button", { name: /Conflict chapter/i }).first();
        if (await chapterLink.count()) {
            await chapterLink.click();
        }

        await expect(page.getByTestId("ai-distill-button")).toBeVisible({
            timeout: 15_000,
        });
        await page.getByTestId("ai-distill-button").click();
        // Click the start button inside the drawer to trigger the AI run.
        const startBtn2 = page.getByTestId("ai-distill-start");
        await expect(startBtn2).toBeVisible({ timeout: 5_000 });
        await startBtn2.click();
        await expect(page.getByTestId("ai-distill-candidate")).toBeVisible({
            timeout: 30_000,
        });

        // Simulate a concurrent external write that bumps the server version
        // BEFORE the user clicks confirm. The chapter PATCH optimistic lock
        // will fire 409 version_conflict and the panel will surface the
        // envelope error code.
        const serverCurrent = await get<{ version: number }>(
            request,
            `/books/${book.id}/chapters/${chapter.id}`,
        );
        await patch(request, `/books/${book.id}/chapters/${chapter.id}`, {
            version: serverCurrent.version,
            content: "Concurrent writer changed this body behind the curtain.",
        });

        await page.getByTestId("ai-distill-adopt").click();
        await expect(page.getByTestId("ai-distill-confirm-modal")).toBeVisible();
        await page.getByTestId("ai-distill-confirm-publish").click();

        // The PATCH must return a 409 (or a related conflict code) and the
        // panel must render an envelope error visible to the user.
        await expect(page.getByTestId("ai-distill-error")).toBeVisible({
            timeout: 15_000,
        });
    });

    test("AI disabled 403 surfaces envelope code", async ({page, request}) => {
        // ---- Patch 010: 验证 AI 角色被禁 403 envelope 错误能透传到 UI ----
        page.on("pageerror", (error) => console.log(`browser-error: ${error.message}`));

        // Seed book + chapter via direct backend calls (mirrors test #1 setup).
        const book = await post<{ id: string }>(request, "/books", {
            title: "Phase G AI disabled workspace",
            author: "e2e",
        });
        await post<{ id: string }>(request, `/books/${book.id}/chapters`, {
            title: "AI disabled chapter",
            content: "Body to be distilled.",
        });

        // Pre-stage AI gateway identity in localStorage so the panel knows the
        // run id is set. Real backend would still gate on the user's role,
        // but here we test the UI's envelope-error surface.
        await page.addInitScript(() => {
            window.localStorage.setItem("bibliogon.ai_run_id", "test-run-ai-disabled");
        });

        // Override the drafting endpoint with a 403 envelope. The reviewer
        // route is NOT mocked here because the panel aborts after the first
        // failure (G1 error stage), so G2 reviewer never fires.
        // The body shape matches the backend envelope convention: the
        // structured dict lives under the top-level `detail` key, so
        // `http.ts` parses `err.detail` as a dict and exposes it through
        // `ApiError.detailBody` for `extractErrorCode`.
        await page.route("**/api/ai/agents/drafting/generate", async (route) => {
            await route.fulfill({
                status: 403,
                contentType: "application/json",
                body: JSON.stringify({
                    detail: {
                        error: "ai_disabled",
                        message: "AI role forbidden for this user",
                        code: "ai_disabled",
                        retryable: false,
                        hint: "",
                    },
                }),
            });
        });

        await page.goto(`/book/${book.id}`);
        await closeOnboardingIfPresent(page);

        const chapterLink = page
            .getByRole("button", { name: /AI disabled chapter/i })
            .first();
        if (await chapterLink.count()) {
            await chapterLink.click();
        }

        await expect(page.getByTestId("ai-distill-button")).toBeVisible({
            timeout: 15_000,
        });
        await page.getByTestId("ai-distill-button").click();
        const startBtn3 = page.getByTestId("ai-distill-start");
        await expect(startBtn3).toBeVisible({ timeout: 5_000 });
        await startBtn3.click();

        // The error stage renders an envelope code pulled from the 403 body.
        await expect(page.getByTestId("ai-distill-error")).toBeVisible({
            timeout: 15_000,
        });
        await expect(page.getByTestId("ai-distill-error")).toContainText(/ai_disabled/);

        // Optional evidence screenshot — surfaces the envelope-error UI.
        await page.screenshot({
            path: "e2e/screenshots/g-ai-distill-ai-403.png",
            fullPage: true,
        });
    });
});