import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { ProjectNode } from "../../api/projectTree";

const trees = ["manuscript", "story_bible", "plot", "research", "archive"] as const;
type TreeType = (typeof trees)[number];
type ChapterChoice = { id: string; title: string };
type Suggestion = { node_type: "volume" | "part" | "chapter" | "scene"; title: string; status: "active" | "draft_placeholder" | "needs_review"; ref_chapter_id?: string; level?: number };

const rules: Record<TreeType, Record<string, string[]>> = {
  manuscript: { volume: [""], part: ["volume"], chapter: ["part"], scene: ["chapter"] },
  story_bible: { grouping: ["", "grouping"] },
  plot: { act: [""], beat: ["act"], beat_detail: ["beat"] },
  research: { note: ["", "note"] },
  archive: { item: ["", "item"] },
};

export default function ProjectOutline({ bookId, chapters, onBack, onReferenceNavigate }: { bookId: string; chapters: ChapterChoice[]; onBack: () => void; onReferenceNavigate: (chapterId: string, paragraphIndex: number) => void }) {
  const [tree, setTree] = useState<TreeType>("manuscript");
  const [nodes, setNodes] = useState<ProjectNode[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [nodeType, setNodeType] = useState("");
  const [filterNodeType, setFilterNodeType] = useState("");
  const [title, setTitle] = useState("");
  const [parentId, setParentId] = useState("");
  const [chapterId, setChapterId] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [references, setReferences] = useState<{id:string; heading_node_id:string; chapter_id:string; status:string; para_index:number; candidate_positions:number[]}[]>([]);
  const [notice, setNotice] = useState("");
  const load = async () => {
    const [nextNodes, nextReferences] = await Promise.all([
      api.projectTree.list(bookId, `?tree_type=${tree}&limit=200`),
      api.projectTree.references(bookId),
    ]);
    setNodes(nextNodes);
    setReferences(nextReferences);
  };
  useEffect(() => { void load(); }, [bookId, tree]);
  const allowedTypes = Object.keys(rules[tree]);
  useEffect(() => { setNodeType(allowedTypes[0]); setFilterNodeType(""); setParentId(""); setTitle(""); setEditing(null); }, [tree]);
  const validParents = nodes.filter(node => rules[tree][nodeType]?.includes(node.node_type));
  // The previous tree's response can remain in state for one render while a
  // tree switch loads. Keep it out of both the view and tree-specific rules.
  const filteredNodes = useMemo(() => nodes.filter(node => node.tree_type === tree && (!keyword || node.title.toLowerCase().includes(keyword.toLowerCase())) && (!status || node.status === status) && (!filterNodeType || node.node_type === filterNodeType)), [nodes, tree, keyword, status, filterNodeType]);
  const children = new Map<string | null, ProjectNode[]>();
  filteredNodes.forEach(node => children.set(node.parent_id, [...(children.get(node.parent_id) ?? []), node]));
  const createNode = async () => {
    if (!title.trim()) return setNotice("A title is required.");
    if (nodeType === "chapter" && !chapterId) return setNotice("Choose the Bibliogon chapter for this manuscript node.");
    await api.projectTree.create(bookId, { tree_type: tree, node_type: nodeType, title: title.trim(), parent_id: parentId || null, ref_chapter_id: nodeType === "chapter" ? chapterId : null });
    setTitle(""); setNotice("Node saved."); await load();
  };
  const move = async (node: ProjectNode, delta: number) => {
    const siblings = (nodes.filter(other => other.parent_id === node.parent_id).sort((a,b) => a.position - b.position));
    const position = Math.max(0, Math.min(siblings.length - 1, node.position + delta));
    await api.projectTree.move(bookId, node.id, node.parent_id, position); await load();
  };
  const renderTree = (parent: string | null, depth = 0): ReactNode[] => (children.get(parent) ?? []).sort((a,b) => a.position - b.position).map(node => {
    const ref = references.find(item => item.heading_node_id === node.id);
    const hasChildren = (children.get(node.id) ?? []).length > 0;
    const isOpen = expanded.has(node.id);
    return <li key={node.id} className="py-1" style={{ paddingLeft: depth * 20 }} data-testid={`project-node-${node.id}`}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border/50 py-1">
        {hasChildren ? <button className="btn btn-ghost btn-sm" aria-label={isOpen ? "Collapse node" : "Expand node"} onClick={() => setExpanded(previous => { const next = new Set(previous); isOpen ? next.delete(node.id) : next.add(node.id); return next; })}>{isOpen ? "-" : "+"}</button> : <span className="w-7" />}
        {editing === node.id ? <><input className="input input-sm" aria-label="Edit node title" value={title} onChange={event => setTitle(event.target.value)} /><button className="btn btn-primary btn-sm" onClick={() => void api.projectTree.update(bookId, node.id, { title }).then(() => { setEditing(null); setTitle(""); return load(); })}>Save</button></> : <><span className="font-medium">{node.title}</span><span className="text-xs text-muted-foreground">{node.node_type} · {node.status}</span></>}
        {ref && <button className={`text-xs ${ref.status === "broken" ? "text-red-600" : ref.status === "needs_relocate" ? "text-yellow-600" : "text-green-600"}`} data-testid={`reference-${ref.status}`} onClick={() => onReferenceNavigate(ref.chapter_id, ref.para_index)}>Reference: {ref.status}{ref.candidate_positions.length ? ` (${ref.candidate_positions.length} candidates)` : ""}</button>}
        <button className="btn btn-ghost btn-sm" aria-label="Edit node" onClick={() => { setEditing(node.id); setTitle(node.title); }}>Edit</button>
        <button className="btn btn-ghost btn-sm" aria-label="Move node up" onClick={() => void move(node, -1)}>Up</button><button className="btn btn-ghost btn-sm" aria-label="Move node down" onClick={() => void move(node, 1)}>Down</button>
        <select aria-label="Move node parent" className="input input-sm" value={node.parent_id ?? ""} onChange={event => void api.projectTree.move(bookId, node.id, event.target.value || null, 0).then(load)}><option value="">Root</option>{nodes.filter(candidate => candidate.id !== node.id && rules[tree][node.node_type]?.includes(candidate.node_type)).map(candidate => <option key={candidate.id} value={candidate.id}>{candidate.title}</option>)}</select>
        <button className="btn btn-ghost btn-sm text-red-600" aria-label="Delete node" onClick={() => void api.projectTree.remove(bookId, node.id).then(load)}>Delete</button>
      </div>
      {hasChildren && isOpen && <ul>{renderTree(node.id, depth + 1)}</ul>}
    </li>;
  });
  const applySuggestions = async () => {
    const levels: Record<string, number> = { volume: 1, part: 2, chapter: 3, scene: 4 };
    const stack: Record<number, number> = {};
    const payload = suggestions.map((item, index) => {
      const level = item.level ?? levels[item.node_type];
      const parent_index = level === 1 ? null : stack[level - 1];
      stack[level] = index;
      Object.keys(stack).map(Number).filter(key => key > level).forEach(key => delete stack[key]);
      return { ...item, parent_index };
    });
    await api.projectTree.applyRebuild(bookId, payload); setSuggestions([]); setNotice("Confirmed suggestions were saved without deleting existing nodes."); await load();
  };
  return <section className="p-6 space-y-4" data-testid="project-outline">
    <div className="flex items-center gap-2"><button className="btn btn-ghost" onClick={onBack}>Back</button><h2>Project Outline</h2></div>
    <div className="flex flex-wrap gap-2" aria-label="Project tree selector">{trees.map(t => <button key={t} className={tree === t ? "btn btn-primary" : "btn btn-secondary"} onClick={() => setTree(t)} data-testid={`tree-${t}`}>{t}</button>)}</div>
    <div className="flex flex-wrap gap-2" data-testid="outline-filters"><input className="input" value={keyword} placeholder="Filter title" onChange={e => setKeyword(e.target.value)} /><select className="input" aria-label="Filter node type" value={filterNodeType} onChange={e => setFilterNodeType(e.target.value)}><option value="">All types</option>{allowedTypes.map(value => <option key={value}>{value}</option>)}</select><select className="input" aria-label="Filter node status" value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option><option value="active">active</option><option value="needs_review">needs_review</option><option value="draft_placeholder">draft_placeholder</option></select></div>
    <div className="grid gap-2 border border-border p-3" data-testid="project-node-form"><input className="input" aria-label="Node title" value={title} placeholder="Node title" onChange={e => setTitle(e.target.value)} /><div className="flex flex-wrap gap-2"><select className="input" aria-label="Node type" value={nodeType} onChange={e => { setNodeType(e.target.value); setParentId(""); }}><option value="">Choose type</option>{allowedTypes.map(value => <option key={value}>{value}</option>)}</select><select className="input" aria-label="Parent node" value={parentId} onChange={e => setParentId(e.target.value)}><option value="">Root</option>{validParents.map(node => <option key={node.id} value={node.id}>{node.node_type}: {node.title}</option>)}</select>{nodeType === "chapter" && <select className="input" aria-label="Linked chapter" value={chapterId} onChange={e => setChapterId(e.target.value)}><option value="">Choose chapter</option>{chapters.map(chapter => <option key={chapter.id} value={chapter.id}>{chapter.title}</option>)}</select>}<button className="btn btn-primary" onClick={() => void createNode()}>Create node</button></div></div>
    {notice && <p role="status" className="text-sm">{notice}</p>}
    <ul data-testid="project-tree-view">{renderTree(null)}</ul>
    {tree === "manuscript" && <div className="space-y-2" data-testid="outline-actions"><div className="flex gap-2"><button className="btn btn-secondary" onClick={() => void api.projectTree.generate(bookId).then(result => setNotice(`Generated ${result.length} root outline nodes.`))}>Generate outline</button><button className="btn btn-secondary" onClick={() => void api.projectTree.rebuild(bookId).then(result => setSuggestions(result as Suggestion[]))}>Rebuild from chapters</button></div>{suggestions.length > 0 && <div className="border border-border p-3" data-testid="rebuild-suggestions"><p className="font-medium">Rebuild suggestions (author review required)</p><ol>{suggestions.map((item, index) => <li key={`${item.title}-${index}`}>{item.node_type}: {item.title} ({item.status})</li>)}</ol><button className="btn btn-primary" onClick={() => void applySuggestions()} data-testid="confirm-rebuild">Confirm rebuild</button></div>}</div>}
  </section>;
}
