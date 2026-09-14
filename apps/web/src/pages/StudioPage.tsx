import type { ProductionRun, ScriptProject, ScriptScene } from "@lifereel/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, BookOpen, Check, Film, Play, RefreshCw, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, generatedAssetUrl, productionSegmentUrl } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";
import { statusLabel } from "../statusLabels";
import { StudioRecovery } from "./StudioRecovery";

function matchesChapter(run: ProductionRun, project: ScriptProject, scene: ScriptScene) {
  if (run.project_id !== project.id) return false;
  const manifest = run.output_manifest;
  if (manifest?.scene_id === scene.id || run.assets.some((asset) => asset.scene_id === scene.id)) return true;
  const snapshot = manifest?.script_snapshot;
  if (snapshot) return snapshot.length === 1 && !!scene.chapter_id && snapshot[0].chapter_id === scene.chapter_id;
  // Old whole-book renders are unambiguous only for a single-chapter book.
  return !manifest?.scene_id && project.scenes.length === 1;
}

function seconds(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? `${Number(value.toFixed(2))} 秒` : "未提供";
}

export function StudioPage() {
  const queryClient = useQueryClient();
  const [searchParams] = useSearchParams();
  const [subjectId, setSubjectId] = useState("");
  const [sceneId, setSceneId] = useState("");
  const [runId, setRunId] = useState("");
  const [view, setView] = useState<"video" | "script">("video");
  const [media, setMedia] = useState<{ id: string; duration: number; width: number; height: number } | null>(null);
  const [mediaError, setMediaError] = useState("");
  const [partial, setPartial] = useState<{ runId: string; index: number } | null>(null);
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const scripts = useQuery({ queryKey: ["scripts"], queryFn: api.listScripts });
  const settings = useQuery({ queryKey: ["production-settings"], queryFn: api.productionSettings });
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: api.wallet, refetchInterval: 10000 });
  const productionRuns = useQuery({
    queryKey: ["production-runs"], queryFn: api.listProductionRuns,
    refetchInterval: (query) => query.state.data?.some((run) => ["queued", "running"].includes(run.status)) ? 3000 : false,
  });
  const terminalRuns = productionRuns.data?.filter((run) => ["completed", "failed", "cancelled"].includes(run.status))
    .map((run) => `${run.id}:${run.status}:${run.updated_at}:${run.output_manifest?.billing?.status}`).join("|");
  useEffect(() => {
    if (terminalRuns) {
      void queryClient.invalidateQueries({ queryKey: ["wallet"] });
      void queryClient.invalidateQueries({ queryKey: ["wallet-ledger"] });
    }
  }, [terminalRuns, queryClient]);
  const publications = useQuery({ queryKey: ["publications"], queryFn: api.listPublications });
  const requestedProject = scripts.data?.find((project) => project.id === searchParams.get("project"));
  const effectiveSubjectId = subjectId || requestedProject?.subject_id || people.data?.find((person) => person.is_subject)?.id || "";
  const entries = (scripts.data ?? []).filter((project) => project.subject_id === effectiveSubjectId)
    .flatMap((project) => [...project.scenes].sort((a, b) => a.order_index - b.order_index).map((scene) => ({ project, scene })));
  const selected = entries.find(({ scene }) => scene.id === sceneId) ?? entries[0];
  const chapterRuns = selected ? (productionRuns.data ?? []).filter((run) => matchesChapter(run, selected.project, selected.scene)) : [];
  const activeRun = chapterRuns.find((run) => run.id === runId) ?? chapterRuns[0];
  const planningIssue = ["VIDEO_PLAN_INVALID", "VIDEO_PLAN_FAILED"].includes(activeRun?.error_message ?? "")
    ? activeRun?.output_manifest?.planning_diagnostics?.at(-1)?.issues[0]?.code : undefined;
  const productionError = statusLabel(planningIssue, statusLabel(activeRun?.error_message, "视频生成失败，请稍后重试。"));
  const activeAsset = activeRun?.assets.find((asset) => asset.mime_type.startsWith("video/"));
  const completedSegments = activeRun?.output_manifest?.segments?.flatMap((segment, index) => segment.status === "completed" ? [{ ...segment, index }] : []) ?? [];
  const selectedPartial = completedSegments.find((segment) => partial?.runId === activeRun?.id && partial?.index === segment.index) ?? completedSegments[0];
  const blocked = activeRun?.status === "failed" && (Boolean(activeRun.recovery) || ["VIDEO_REFERENCE_REJECTED", "VIDEO_CONTENT_REJECTED"].includes(activeRun.error_message ?? ""));
  const blocksCurrentScript = blocked && (activeRun?.output_manifest?.script_version ?? selected?.project.version_number) === selected?.project.version_number;
  const publication = publications.data?.find((item) => item.production_run_id === activeRun?.id && item.status === "published");
  const isGenerating = chapterRuns.some((run) => ["queued", "running"].includes(run.status));
  const displayedScene = activeRun?.output_manifest?.script_snapshot?.[0] ?? selected?.scene;
  const actualMedia = media?.id === activeAsset?.id ? media : null;
  const parameters = activeAsset?.generation_parameters;
  const segmented = settings.data?.mode === "segmented";
  const quote = wallet.data?.prices && selected ? wallet.data.prices.video_billing_mode === "tokens" && settings.data?.provider !== "mock"
    ? wallet.data.prices.video_reserve_cents
    : (segmented ? selected.scene.duration_seconds : settings.data?.duration_seconds ?? selected.scene.duration_seconds) * wallet.data.prices.video_cents_per_second : undefined;
  const hasBalance = (wallet.data?.available_cents ?? 0) > 0;
  const progress = activeRun?.output_manifest;
  const progressText = activeRun?.status === "running" && progress?.stage
    ? progress.stage === "planning" ? "正在规划分镜"
      : progress.stage === "assembling" ? "正在拼接整章视频"
        : `已完成 ${progress.completed_segments ?? 0} / ${progress.segments?.length ?? 0} 段`
    : null;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["production-runs"] });
  const produce = useMutation({
    mutationFn: ({ project, scene }: { project: ScriptProject; scene: ScriptScene }) => api.startProduction({ project_id: project.id, scene_id: scene.id, audience: "family", quoted_amount_cents: quote }),
    onSuccess: async (run) => { setRunId(run.id); setView("video"); await queryClient.invalidateQueries({ queryKey: ["wallet"] }); await refresh(); },
  });
  const publish = useMutation({ mutationFn: (id: string) => api.publish(id, "family"), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["publications"] }) });
  const withdraw = useMutation({ mutationFn: api.withdrawPublication, onSuccess: () => queryClient.invalidateQueries({ queryKey: ["publications"] }) });
  const retry = useMutation({ mutationFn: api.retryJob, onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: ["wallet"] });
    await refresh();
  } });
  const refreshSettlement = async () => {
    await queryClient.invalidateQueries({ queryKey: ["wallet"] });
    await refresh();
  };
  const queries = [people, scripts, settings, productionRuns, publications, wallet];

  return <div className="page film-studio-page">
    <header className="page-title-row studio-title">
      <div><span className="eyebrow">人生影像</span><h1>影像制作</h1></div>
      <Link className="button secondary" to={effectiveSubjectId ? `/scripts/${effectiveSubjectId}` : "/scripts"}><BookOpen size={17} aria-hidden="true" /> 返回剧本书册</Link>
    </header>
    {hasQueryIssue(queries) ? <QueryState queries={queries} loadingText="正在准备影像制作台……" /> : <>
      <ErrorNotice error={produce.error || publish.error || withdraw.error || retry.error} />
      <div className="studio-workspace">
        <aside className="studio-catalog" aria-label="制作章节">
          <label>制作对象<select value={effectiveSubjectId} onChange={(event) => { setSubjectId(event.target.value); setSceneId(""); setRunId(""); }}>
            {!people.data?.some((person) => person.is_subject) && <option value="">暂无家人</option>}
            {people.data?.filter((person) => person.is_subject).map((person) => <option key={person.id} value={person.id}>{person.preferred_name || person.display_name}</option>)}
          </select></label>
          <div className="studio-catalog-heading"><h2>章节剧本</h2><span>{entries.length} 章</span></div>
          <nav className="studio-chapters" aria-label="章节列表">
            {entries.map(({ project, scene }, index) => {
              const run = productionRuns.data?.find((item) => matchesChapter(item, project, scene));
              return <button key={scene.id} aria-current={selected?.scene.id === scene.id ? "true" : undefined} onClick={() => { setSceneId(scene.id); setRunId(""); }}>
                <span className="studio-chapter-number">{String(index + 1).padStart(2, "0")}</span>
                <span><strong>{scene.heading}</strong><small>剧本约 {scene.duration_seconds} 秒</small><small className="studio-chapter-status">{run ? statusLabel(run.status) : "尚未生成"}</small></span>
                {run?.status === "completed" && <Check size={16} aria-hidden="true" />}
              </button>;
            })}
          </nav>
          {!entries.length && <p className="studio-muted">暂无章节剧本</p>}
        </aside>
        <section className="studio-detail" aria-label="章节影像工作台">
          {selected ? <>
            <div className="studio-parameters">
              <div className="studio-selection-heading"><div><span className="eyebrow">当前章节</span><h2>{selected.scene.heading}</h2></div><span className="studio-mode-label">{segmented ? "整章生成" : "试生成片段"}</span></div>
              <dl className="studio-specs" aria-label="视频参数">
                <div><dt>目标画质</dt><dd>{settings.data?.resolution ?? "由服务决定"}</dd></div>
                <div><dt>画面比例</dt><dd>{settings.data?.ratio ?? "由服务决定"}</dd></div>
                <div><dt>目标时长</dt><dd>{seconds(segmented ? selected.scene.duration_seconds : settings.data?.duration_seconds)}</dd></div>
                <div><dt>声音</dt><dd>{settings.data?.generate_audio === true ? "原生音频" : settings.data?.generate_audio === false ? "无声片段" : "由服务决定"}</dd></div>
              </dl>
              <div className="studio-generate-row"><span className="studio-muted">剧本预估 {seconds(selected.scene.duration_seconds)}</span><button className="button primary" disabled={produce.isPending || isGenerating || quote === undefined || !hasBalance || blocksCurrentScript} title={blocksCurrentScript ? "请先处理下方的审核问题" : !hasBalance ? "余额不足，请先充值" : undefined} onClick={() => produce.mutate(selected)}><Play size={16} aria-hidden="true" /> {isGenerating ? "正在生成" : "生成影像"}</button></div>
            </div>
            <div className="studio-preview-toolbar">
              <div role="tablist" aria-label="预览内容" className="studio-tabs" onKeyDown={(event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                event.preventDefault();
                const next = event.key === "Home" ? "video" : event.key === "End" ? "script" : view === "video" ? "script" : "video";
                setView(next);
                document.getElementById(`studio-tab-${next}`)?.focus();
              }}>
                <button id="studio-tab-video" role="tab" aria-selected={view === "video"} aria-controls="studio-panel-video" tabIndex={view === "video" ? 0 : -1} onClick={() => setView("video")}><Film size={17} aria-hidden="true" /> 视频预览</button>
                <button id="studio-tab-script" role="tab" aria-selected={view === "script"} aria-controls="studio-panel-script" tabIndex={view === "script" ? 0 : -1} onClick={() => setView("script")}><BookOpen size={17} aria-hidden="true" /> 本章剧本</button>
              </div>
              {activeRun && <span className={`run-status ${activeRun.status}`} role="status">{statusLabel(activeRun.status)}</span>}
            </div>
            {chapterRuns.length > 1 && <label className="studio-version">生成版本<select value={activeRun?.id} onChange={(event) => setRunId(event.target.value)}>{chapterRuns.map((run, index) => <option key={run.id} value={run.id}>{index === 0 ? "最新 · " : ""}{new Date(run.created_at).toLocaleString("zh-CN")} · {statusLabel(run.status)}</option>)}</select></label>}
            {progressText && <p className="studio-muted" role="status">{progressText}</p>}
            <div id="studio-panel-video" role="tabpanel" aria-labelledby="studio-tab-video" hidden={view !== "video"}>
              {activeRun?.error_message && <div className="notice error" role="alert">{productionError}{activeRun.job_id && !blocked && <button className="button secondary small" disabled={retry.isPending || (!hasBalance && activeRun.output_manifest?.billing?.status !== "pending")} onClick={() => retry.mutate(activeRun.job_id!)}><RefreshCw size={15} aria-hidden="true" /> 重新尝试</button>}</div>}
              {activeRun?.recovery?.code === "VIDEO_REFERENCE_REJECTED" && <StudioRecovery key={`${activeRun.id}:${activeRun.updated_at}`} run={activeRun} subjectId={effectiveSubjectId} canSpend={hasBalance || activeRun.output_manifest?.billing?.status === "pending"} onSettled={refreshSettlement} />}
              {blocked && activeRun?.error_message === "VIDEO_CONTENT_REJECTED" && <Link to={`/scripts/${effectiveSubjectId}`}>查看并修改剧本</Link>}
              {!activeAsset && selectedPartial && activeRun && <label className="studio-version">已完成片段<select value={selectedPartial.index} onChange={(event) => setPartial({ runId: activeRun.id, index: Number(event.target.value) })}>
                {completedSegments.map((segment) => <option key={segment.index} value={segment.index}>第 {segment.index + 1} 段 · {seconds(segment.duration_seconds)}</option>)}
              </select><span>已完成 {completedSegments.length} / {activeRun.output_manifest?.segments?.length} 段，整章尚未完成</span></label>}
              <div className="studio-screen">
                {activeAsset ? <video key={activeAsset.id} aria-label={`${selected.scene.heading}视频`} controls playsInline preload="metadata" src={generatedAssetUrl(activeAsset.id)} onLoadedMetadata={(event) => {
                  const video = event.currentTarget;
                  setMedia({ id: activeAsset.id, duration: video.duration, width: video.videoWidth, height: video.videoHeight });
                  setMediaError("");
                }} onError={() => setMediaError(activeAsset.id)} /> : selectedPartial && activeRun ? <video key={`${activeRun.id}:${selectedPartial.index}`} aria-label={`第 ${selectedPartial.index + 1} 段视频`} controls playsInline preload="metadata" src={productionSegmentUrl(activeRun.id, selectedPartial.index)} onError={() => setMediaError(`${activeRun.id}:${selectedPartial.index}`)} /> : <EmptyState icon={Film} title={isGenerating ? "正在生成本章影像" : activeRun?.status === "failed" ? "本次生成未完成" : "本章尚无影像"} description={isGenerating ? "等待生成结果" : ""} />}
              </div>
              {activeAsset && mediaError === activeAsset.id && <div className="notice error" role="alert">视频加载失败，请检查网络后重试。</div>}
              {!activeAsset && selectedPartial && mediaError === `${activeRun?.id}:${selectedPartial.index}` && <div className="notice error" role="alert">片段加载失败，请稍后刷新页面。</div>}
              {activeAsset && <div className="studio-output-meta"><span>实际时长 {seconds(actualMedia?.duration)}</span><span>实际尺寸 {actualMedia ? `${actualMedia.width} × ${actualMedia.height}` : "读取中"}</span><span>{parameters?.generate_audio === false ? "无声" : parameters?.generate_audio === true ? "有声" : "声音信息未提供"}</span></div>}
              {activeAsset && <div className="studio-publish-row">{publication ? <><span className="studio-muted">已发布给家人</span><button className="button secondary small danger" disabled={withdraw.isPending} onClick={() => withdraw.mutate(publication.id)}><Ban size={15} aria-hidden="true" /> 撤回发布</button></> : <button className="button secondary small" disabled={publish.isPending || activeRun?.status !== "completed"} onClick={() => activeRun && publish.mutate(activeRun.id)}><Send size={16} aria-hidden="true" /> 发布给家人</button>}</div>}
            </div>
            <div id="studio-panel-script" role="tabpanel" aria-labelledby="studio-tab-script" hidden={view !== "script"}>
              <article className="studio-script">
                <div className="studio-script-caption"><span>{activeRun?.output_manifest?.script_snapshot ? "生成时剧本" : "当前剧本"}</span><span>预估 {seconds(displayedScene?.duration_seconds)}</span></div>
                {activeRun && !activeRun.output_manifest?.script_snapshot && <p className="notice">此历史视频未保存剧本快照，以下为当前章节内容。</p>}
                {activeRun?.output_manifest?.script_version != null && activeRun.output_manifest.script_version !== selected.project.version_number && <p className="notice">剧本已更新，以下保留本次视频生成时的内容。</p>}
                <h3>{displayedScene?.heading}</h3>
                <h4>旁白</h4><p>{displayedScene?.narration || "暂无旁白"}</p>
                <h4>画面描述</h4><p>{displayedScene?.visual_prompt || "暂无画面描述"}</p>
              </article>
            </div>
          </> : <EmptyState icon={BookOpen} title="还没有可制作的章节" description="" />}
        </section>
      </div>
    </>}
  </div>;
}
