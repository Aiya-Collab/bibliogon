import { request } from "./http";

export type ProjectNode = { id: string; tree_type: string; parent_id: string | null; node_type: string; title: string; position: number; ref_chapter_id: string | null; status: string };

export const projectTreeApi = {
  projectTree: {
    list: (bookId: string, query = "") => request<ProjectNode[]>(`/books/${bookId}/project-tree${query}`),
    create: (bookId: string, data: Record<string, unknown>) => request<ProjectNode>(`/books/${bookId}/project-tree`, { method: "POST", body: JSON.stringify(data) }),
    update: (bookId: string, nodeId: string, data: Record<string, unknown>) => request<ProjectNode>(`/books/${bookId}/project-tree/${nodeId}`, { method: "PATCH", body: JSON.stringify(data) }),
    remove: (bookId: string, nodeId: string) => request<void>(`/books/${bookId}/project-tree/${nodeId}`, { method: "DELETE" }),
    move: (bookId: string, nodeId: string, parent_id: string | null, position: number) => request<ProjectNode>(`/books/${bookId}/project-tree/${nodeId}/move`, { method: "POST", body: JSON.stringify({ parent_id, position }) }),
    generate: (bookId: string) => request<ProjectNode[]>(`/books/${bookId}/project-tree/outline/generate`),
    rebuild: (bookId: string) => request<Record<string, unknown>[]>(`/books/${bookId}/project-tree/rebuild`, { method: "POST" }),
    applyRebuild: (bookId: string, nodes: Record<string, unknown>[]) => request<ProjectNode[]>(`/books/${bookId}/project-tree/rebuild-apply`, { method: "POST", body: JSON.stringify({ nodes }) }),
    references: (bookId: string) => request<{id:string; heading_node_id:string; chapter_id:string; para_index:number; status:string; candidate_positions:number[]}[]>(`/references?book_id=${bookId}`),
  },
};
