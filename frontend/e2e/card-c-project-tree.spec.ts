import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const backend = "http://127.0.0.1:8000/api";

async function post<T>(request: APIRequestContext, path: string, body: unknown): Promise<T> {
  const response = await request.post(`${backend}${path}`, { data: body });
  expect(response.ok(), `${path}: ${await response.text()}`).toBeTruthy();
  return response.json() as Promise<T>;
}

async function createUiNode(page: Page, type: string, title: string, parent?: string, chapter?: string) {
  const form = page.getByTestId("project-node-form");
  await form.getByLabel("Node type").selectOption(type);
  if (parent) await form.getByLabel("Parent node").selectOption({ label: parent });
  if (chapter) await form.getByLabel("Linked chapter").selectOption(chapter);
  await form.getByLabel("Node title").fill(title);
  await form.getByRole("button", { name: "Create node" }).click();
  await expect(page.getByText("Node saved.", { exact: true })).toBeVisible();
}

async function expandAllVisibleNodes(page: Page) {
  await expect(page.getByRole("button", { name: "Expand node" }).first()).toBeVisible();
  for (let index = 0; index < 4; index += 1) {
    const expand = page.getByRole("button", { name: "Expand node" }).first();
    if (!await expand.count()) return;
    await expand.click();
  }
}

test("Card C: five trees, outline operations, references, and rebuild confirmation", async ({ page, request }) => {
  test.setTimeout(120_000);
  page.on("pageerror", (error) => console.log(`browser-error: ${error.message}`));
  const book = await post<{ id: string }>(request, "/books", { title: "Card C browser workspace", author: "e2e" });
  const chapter = await post<{ id: string }>(request, `/books/${book.id}/chapters`, { title: "Chapter one", content: "one target tail\nsecond paragraph" });

  await page.goto(`/book/${book.id}`);
  // BookEditor restores the upstream mobile/sidebar overlay state. Close it
  // as a user would before operating the work surface.
  // The onboarding dialog mounts after the editor's initial render. Its
  // accessible close control is stable; wait briefly so this does not race.
  const setupClose = page.getByRole("button", { name: "Close" });
  const hasSetup = await expect(setupClose).toBeVisible({ timeout: 15_000 }).then(() => true).catch(() => false);
  if (hasSetup) {
    await setupClose.click();
    await expect(setupClose).toBeHidden();
  }
  await page.getByTestId("book-editor-project-outline").click();
  await expect(page.getByTestId("project-outline")).toBeVisible();

  await createUiNode(page, "volume", "Volume I");
  await createUiNode(page, "part", "Part I", "volume: Volume I");
  await createUiNode(page, "chapter", "Chapter I", "part: Part I", chapter.id);
  await createUiNode(page, "scene", "Scene I", "chapter: Chapter I");
  await expandAllVisibleNodes(page);
  await expect(page.getByText("Scene I", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Generate outline" }).click();
  await expect(page.getByText(/Generated .* root outline nodes/)).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/card-c-four-level-tree.png", fullPage: true });

  for (const [tree, type, title] of [["story_bible", "grouping", "Bible theme"], ["plot", "act", "Act I"], ["research", "note", "Research A"], ["archive", "item", "Archive A"]] as const) {
    await page.getByTestId(`tree-${tree}`).click();
    await createUiNode(page, type, title);
    await expect(page.getByText(title, { exact: true })).toBeVisible();
  }
  await page.getByTestId("tree-story_bible").click();
  await createUiNode(page, "grouping", "Character thread", "grouping: Bible theme");
  await page.getByLabel("Edit node").first().click();
  await page.getByLabel("Edit node title").fill("Bible theme revised");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Bible theme revised", { exact: true })).toBeVisible();
  await page.getByTestId("tree-archive").click();
  await page.getByLabel("Edit node").click();
  await page.getByLabel("Edit node title").fill("Archive revised");
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByLabel("Delete node").click();
  await expect(page.getByTestId("project-tree-view").getByText("Archive revised", { exact: true })).toHaveCount(0);
  await createUiNode(page, "item", "Archive A");
  await page.screenshot({ path: "e2e/screenshots/card-c-five-trees.png", fullPage: true });

  await page.getByTestId("tree-story_bible").click();
  await page.getByPlaceholder("Filter title").fill("revised");
  await expect(page.getByText("Bible theme revised", { exact: true })).toBeVisible();
  await expect(page.getByTestId("project-tree-view").getByText("Character thread", { exact: true })).toBeHidden();
  await page.getByPlaceholder("Filter title").fill("");
  await page.reload();
  await page.getByTestId("book-editor-project-outline").click();
  await expect(page.getByTestId("project-outline")).toBeVisible();
  await page.getByTestId("tree-story_bible").click();
  await expect(page.getByText("Bible theme revised", { exact: true })).toBeVisible();

  await page.getByTestId("tree-manuscript").click();
  await createUiNode(page, "volume", "Volume II");
  await page.getByRole("button", { name: "Move node down" }).first().click();
  const manuscriptNodes = await (await request.get(`${backend}/books/${book.id}/project-tree?tree_type=manuscript`)).json();
  const manuscriptChapter = manuscriptNodes.find((node: { node_type: string }) => node.node_type === "chapter");
  const scene = await post<{ id: string }>(request, `/books/${book.id}/project-tree`, { tree_type: "manuscript", node_type: "scene", title: "Reference scene", parent_id: manuscriptChapter.id });
  await post(request, `/references/scene/${scene.id}`, { chapter_id: chapter.id, anchor_before: "one ", anchor_at: "target", anchor_after: " tail", para_index: 0 });
  await post(request, `/references/resolve?chapter_id=${chapter.id}`, {});
  await page.reload();
  await page.getByTestId("book-editor-project-outline").click();
  await expandAllVisibleNodes(page);
  await expect(page.getByTestId("reference-valid")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/card-c-reference-valid.png", fullPage: true });

  const latestBody = await (await request.get(`${backend}/books/${book.id}/chapters/${chapter.id}`)).json();
  const relocated = await request.patch(`${backend}/books/${book.id}/chapters/${chapter.id}`, { data: { content: "one target tail\none target tail", version: latestBody.version } });
  expect(relocated.ok()).toBeTruthy();
  await page.reload();
  await page.getByTestId("book-editor-project-outline").click();
  await expandAllVisibleNodes(page);
  await expect(page.getByTestId("reference-needs_relocate")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/card-c-reference-needs-relocate.png", fullPage: true });

  const latestForBroken = await (await request.get(`${backend}/books/${book.id}/chapters/${chapter.id}`)).json();
  const patched = await request.patch(`${backend}/books/${book.id}/chapters/${chapter.id}`, { data: { content: "anchor removed", version: latestForBroken.version } });
  expect(patched.ok()).toBeTruthy();
  await page.reload();
  await page.getByTestId("book-editor-project-outline").click();
  await expandAllVisibleNodes(page);
  await expect(page.getByTestId("reference-broken")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/card-c-reference-states.png", fullPage: true });

  const headingDocument = JSON.stringify({ type: "doc", content: [{ type: "heading", attrs: { level: 1 }, content: [{ type: "text", text: "Rebuilt volume" }] }, { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Rebuilt part" }] }] });
  const afterPatch = await (await request.get(`${backend}/books/${book.id}/chapters/${chapter.id}`)).json();
  await request.patch(`${backend}/books/${book.id}/chapters/${chapter.id}`, { data: { content: headingDocument, version: afterPatch.version } });
  await page.getByRole("button", { name: "Rebuild from chapters" }).click();
  await expect(page.getByTestId("rebuild-suggestions")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/card-c-rebuild-confirm.png", fullPage: true });
  await page.getByTestId("confirm-rebuild").click();
  await expect(page.getByText(/Confirmed suggestions were saved/)).toBeVisible();

  await page.getByRole("button", { name: /Reference: broken/ }).click();
  await expect(page.getByRole("textbox", { name: "Editor" })).toBeVisible();
});
