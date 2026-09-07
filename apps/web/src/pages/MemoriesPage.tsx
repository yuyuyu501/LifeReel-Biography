import { useQuery } from "@tanstack/react-query";
import {
  Archive,
  CalendarDays,
  ExternalLink,
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  Link2,
  Network,
  TriangleAlert,
  UserRound,
} from "lucide-react";
import { useMemo, useState } from "react";
import { api, evidenceAssetUrl } from "../api/client";
import { formatAssetBytes } from "../assetFormatting";
import { AssetPreview } from "../components/AssetPreview";
import { EmptyState } from "../components/EmptyState";
import { MemoryGraph } from "../components/MemoryGraph";
import { QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";
import { statusLabel } from "../statusLabels";

const FILE_TYPES = [
  { kind: "all", label: "全部", icon: Archive },
  { kind: "photo", label: "图片", icon: FileImage },
  { kind: "document", label: "文档", icon: FileText },
  { kind: "audio", label: "音频", icon: FileAudio },
  { kind: "video", label: "视频", icon: FileVideo },
] as const;

type FileKind = (typeof FILE_TYPES)[number]["kind"];

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function assetIcon(kind: string) {
  if (kind === "audio") return FileAudio;
  if (kind === "photo") return FileImage;
  if (kind === "video") return FileVideo;
  return FileText;
}

function nodeKindLabel(kind: string) {
  if (kind === "subject") return "主人公";
  if (kind === "event") return "人生事件";
  return statusLabel(kind, "记忆节点");
}

function compactBiography(text: string) {
  const normalized = text.replace(/[#*`\n]+/g, " ").replace(/\s+/g, " ").trim();
  return normalized.length > 260 ? `${normalized.slice(0, 260)}…` : normalized;
}

export function MemoriesPage() {
  const [subjectId, setSubjectId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [fileKind, setFileKind] = useState<FileKind>("all");
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const subjects = people.data?.filter((person) => person.is_subject) ?? [];
  const subject = subjects.find((item) => item.id === subjectId) ?? subjects[0];
  const memories = useQuery({ queryKey: ["memories", subject?.id], queryFn: () => api.listMemories(subject!.id), enabled: Boolean(subject) });
  const overview = useQuery({ queryKey: ["memory-overview", subject?.id], queryFn: () => api.memoryOverview(subject!.id), enabled: Boolean(subject) });
  const graph = useQuery({ queryKey: ["memory-graph", subject?.id], queryFn: () => api.getMemoryGraph(subject!.id), enabled: Boolean(subject) });
  const timeline = useQuery({ queryKey: ["memory-timeline", subject?.id], queryFn: () => api.listMemoryTimeline(subject!.id), enabled: Boolean(subject) });
  const conflicts = useQuery({ queryKey: ["memory-conflicts", subject?.id], queryFn: () => api.listMemoryConflicts(subject!.id), enabled: Boolean(subject) });
  const files = useQuery({ queryKey: ["evidence", subject?.id], queryFn: () => api.listEvidence(subject!.id), enabled: Boolean(subject) });

  const subjectQueries = subject ? [memories, overview, graph, timeline, conflicts, files] : [];
  const selectedNode = graph.data?.nodes.find((node) => node.id === selectedNodeId)
    ?? graph.data?.nodes.find((node) => node.kind === "subject")
    ?? graph.data?.nodes[0];
  const selectedClaims = useMemo(() => {
    const ids = new Set(selectedNode?.source_claim_ids ?? []);
    return memories.data?.filter((claim) => ids.has(claim.id)) ?? [];
  }, [memories.data, selectedNode]);
  const profileSummary = subject?.biography_note
    || compactBiography(memories.data?.slice(0, 2).map((claim) => claim.claim_text).join(" ") ?? "")
    || "人物介绍会随着采访逐步完善。目前可先从关系图谱、人生事件和相关文件了解这份档案。";
  const visibleFiles = files.data?.filter((asset) => fileKind === "all" || asset.kind === fileKind) ?? [];
  const selectedAsset = visibleFiles.find((asset) => asset.id === selectedAssetId) ?? visibleFiles[0];

  function chooseSubject(id: string) {
    setSubjectId(id);
    setSelectedNodeId("");
    setSelectedAssetId("");
    setFileKind("all");
  }

  function chooseFileType(kind: FileKind) {
    setFileKind(kind);
    setSelectedAssetId("");
  }

  return (
    <div className="page memory-archive-page">
      <header className="page-title-row memory-title-row">
        <div>
          <span className="eyebrow">人物、关系、事件与原始记录</span>
          <h1>记忆档案</h1>
          <p className="page-intro">采访中的讲述与文件会按人物归档，形成可追溯的关系图谱和人生时间线。</p>
        </div>
        {subjects.length > 0 && (
          <label className="memory-subject-picker">当前人物
            <select value={subject?.id ?? ""} onChange={(event) => chooseSubject(event.target.value)}>
              {subjects.map((person) => <option key={person.id} value={person.id}>{person.preferred_name || person.display_name}</option>)}
            </select>
          </label>
        )}
      </header>

      {hasQueryIssue([people]) ? <QueryState queries={[people]} loadingText="正在读取人物档案……" /> : !subject ? (
        <EmptyState icon={UserRound} title="还没有人物档案" description="建立人物并开始采访后，讲述和文件会在这里形成专属记忆档案。" />
      ) : hasQueryIssue(subjectQueries) ? (
        <QueryState queries={subjectQueries} loadingText={`正在整理${subject.preferred_name || subject.display_name}的记忆档案……`} />
      ) : <>
        <section className="memory-profile" aria-labelledby="memory-profile-title">
          <div className="memory-profile-mark" aria-hidden="true">{(subject.preferred_name || subject.display_name).slice(0, 1)}</div>
          <div className="memory-profile-copy">
            <span className="eyebrow">人物小传</span>
            <h2 id="memory-profile-title">{subject.preferred_name || subject.display_name}</h2>
            <p>{profileSummary}</p>
          </div>
          <dl className="memory-profile-facts">
            <div><dt>出生年份</dt><dd>{subject.birth_year ? `${subject.birth_year} 年` : "待补充"}</dd></div>
            <div><dt>出生地点</dt><dd>{subject.birthplace || "待补充"}</dd></div>
            <div><dt>家庭称谓</dt><dd>{subject.relation_to_owner || "待补充"}</dd></div>
          </dl>
        </section>

        <div className="memory-stats" aria-label="记忆档案概览">
          <span><strong>{overview.data?.claim_count ?? 0}</strong> 条采访记忆</span>
          <span><strong>{Math.max(0, (graph.data?.nodes.length ?? 1) - 1)}</strong> 个关系节点</span>
          <span><strong>{overview.data?.timeline_count ?? 0}</strong> 个人生事件</span>
          <span><strong>{files.data?.length ?? 0}</strong> 份回忆文件</span>
          <span><strong>{Math.round((overview.data?.coverage_ratio ?? 0) * 100)}%</strong> 章节覆盖</span>
        </div>

        <section className="memory-section" aria-labelledby="memory-graph-heading">
          <div className="section-heading">
            <div><span className="eyebrow">采访生成 · 来源可追溯</span><h2 id="memory-graph-heading">人物关系图谱</h2></div>
            <div className="memory-graph-legend" aria-label="图谱图例">
              <span><i className="is-person" />人物</span><span><i className="is-place" />地点</span><span><i className="is-organization" />组织</span><span><i className="is-event" />事件</span>
            </div>
          </div>
          {graph.data && graph.data.nodes.length > 1 ? (
            <div className="memory-graph-workspace">
              <div className="memory-graph-main">
                <MemoryGraph graph={graph.data} selectedNodeId={selectedNode?.id ?? ""} onSelectNode={(node) => setSelectedNodeId(node.id)} />
              </div>
              <aside className="memory-node-inspector" aria-live="polite">
                {selectedNode && <>
                  <span className="node-type">{nodeKindLabel(selectedNode.kind)}</span>
                  <h3>{selectedNode.label}</h3>
                  <p>{selectedNode.description || (selectedNode.kind === "subject" ? profileSummary : "选择关联记录可查看采访来源。")}</p>
                  {selectedNode.time_text && <time><CalendarDays size={15} />{selectedNode.time_text}</time>}
                  <div className="node-source-list">
                    <strong><Link2 size={14} />相关采访记录</strong>
                    {selectedClaims.length ? selectedClaims.map((claim) => <blockquote key={claim.id}>{claim.source_quote || claim.claim_text}</blockquote>) : <small>{selectedNode.kind === "subject" ? "选择外侧节点查看支撑这段关系的采访原话。" : "暂无可展示的采访原话。"}</small>}
                  </div>
                </>}
              </aside>
              <div className="memory-relationship-index" aria-label="关系索引">
                <span className="eyebrow">关系索引</span>
                {graph.data.edges.length ? <ul>{graph.data.edges.map((edge) => {
                  const target = graph.data?.nodes.find((node) => node.id === edge.target_id);
                  if (!target) return null;
                  return <li key={edge.id}><button type="button" aria-pressed={selectedNode?.id === target.id} onClick={() => setSelectedNodeId(target.id)}><span>{edge.relationship}</span><strong>{target.label}</strong><small>{edge.source_claim_ids.length} 条来源</small></button></li>;
                })}</ul> : <p>采访中出现明确人物、地点或事件后会建立关系。</p>}
              </div>
            </div>
          ) : <EmptyState icon={Network} title="关系图谱正在等待内容" description="继续采访，提到家人、地点、组织或人生事件后，这里会自动形成有来源的关系。" />}
        </section>

        <section className="memory-section" aria-labelledby="memory-timeline-heading">
          <div className="section-heading"><div><span className="eyebrow">人生轨迹</span><h2 id="memory-timeline-heading">事件时间线</h2></div><p>年份和“小时候”等人生阶段均来自采访原话。</p></div>
          {timeline.data?.length ? <div className="memory-timeline">{timeline.data.map((anchor) => <article key={anchor.id}><time>{anchor.year ?? anchor.time_text}</time><div><strong>{anchor.event_text}</strong><small>{statusLabel(anchor.precision, "时间线索")}</small></div></article>)}</div> : <EmptyState icon={CalendarDays} title="还没有人生事件" description="采访中出现明确年份或人生阶段后，事件会按时间沉淀在这里。" />}
        </section>

        <section className="memory-section" aria-labelledby="memory-files-heading">
          <div className="section-heading"><div><span className="eyebrow">来自采访聊天</span><h2 id="memory-files-heading">回忆文件</h2></div><p>这里只保存和查看人物相关资料；新增文件请在对应章节的采访中完成。</p></div>
          {files.data?.length ? <div className="memory-files-workspace">
            <aside className="memory-file-browser">
              <div className="memory-file-tabs" role="tablist" aria-label="回忆文件类型">
                {FILE_TYPES.map(({ kind, label, icon: Icon }) => {
                  const count = kind === "all" ? files.data?.length : files.data?.filter((asset) => asset.kind === kind).length;
                  return <button key={kind} type="button" role="tab" aria-selected={fileKind === kind} className={fileKind === kind ? "active" : ""} onClick={() => chooseFileType(kind)}><Icon size={16} aria-hidden="true" />{label}<small>{count ?? 0}</small></button>;
                })}
              </div>
              {visibleFiles.length ? <ul className="memory-file-list">{visibleFiles.map((asset) => {
                const Icon = assetIcon(asset.kind);
                return <li key={asset.id}><button type="button" aria-pressed={selectedAsset?.id === asset.id} onClick={() => setSelectedAssetId(asset.id)}><span><Icon size={19} aria-hidden="true" /></span><div><strong>{asset.original_filename}</strong><small>{formatDate(asset.created_at)} · {formatAssetBytes(asset.byte_size)}</small></div></button></li>;
              })}</ul> : <div className="memory-file-empty">此分类暂无文件</div>}
            </aside>
            <div className="memory-file-viewer">
              {selectedAsset ? <>
                <header><div><span>{statusLabel(selectedAsset.kind, "文件")}</span><h3>{selectedAsset.original_filename}</h3></div><a className="icon-button" href={evidenceAssetUrl(selectedAsset.id)} target="_blank" rel="noreferrer" aria-label="在新窗口打开文件" title="在新窗口打开"><ExternalLink size={17} /></a></header>
                <div className={`memory-file-stage is-${selectedAsset.kind}`}><AssetPreview asset={selectedAsset} /></div>
              </> : <div className="memory-file-empty">选择左侧文件后在这里查看</div>}
            </div>
          </div> : <EmptyState icon={Archive} title="还没有回忆文件" description="在采访聊天中上传照片、音频、视频或文档后，它们会自动归入当前人物。" />}
        </section>

        {conflicts.data?.length ? <section className="memory-conflicts" aria-labelledby="memory-conflicts-heading">
          <div><TriangleAlert size={21} /><div><span className="eyebrow">待核对</span><h2 id="memory-conflicts-heading">记忆冲突</h2></div></div>
          <ul>{conflicts.data.map((conflict) => <li key={conflict.id}><strong>{conflict.description}</strong><small>涉及 {conflict.claim_ids.length} 条采访记忆 · {statusLabel(conflict.status)}</small></li>)}</ul>
        </section> : null}
      </>}
    </div>
  );
}
