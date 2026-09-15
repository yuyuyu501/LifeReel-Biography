import type { SourceAsset } from "@lifereel/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp,
  BookOpenText,
  Check,
  CheckCircle2,
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  LoaderCircle,
  Mic2,
  Paperclip,
  RefreshCw,
  Square,
  Trash2,
} from "lucide-react";
import { type ChangeEvent, type FormEvent, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { ApiError, errorMessage } from "../api/errors";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { EditableScript } from "../components/EditableScript";
import {
  EVIDENCE_LIMITS,
  EVIDENCE_LIMIT_SUMMARY,
  evidenceKindFromMime,
  type EvidenceKind,
} from "../evidenceLimits";
import { useAudioRecorder } from "../hooks/useAudioRecorder";

const kindIcon = {
  audio: FileAudio,
  photo: FileImage,
  video: FileVideo,
  document: FileText,
};

function fileKind(file: File): EvidenceKind | null {
  const detected = evidenceKindFromMime(file.type);
  if (detected) return detected;
  const suffix = file.name.split(".").pop()?.toLowerCase();
  if (["pdf", "txt", "md"].includes(suffix ?? "")) return "document";
  return null;
}

function Attachment({ asset }: { asset: SourceAsset }) {
  const Icon = kindIcon[asset.kind as EvidenceKind] ?? FileText;
  return (
    <div className="chat-asset">
      <Icon size={17} />
      <span title={asset.original_filename}>{asset.original_filename}</span>
      <small>{asset.consent_scope === "private" ? "仅自己可见" : "家庭素材"}</small>
    </div>
  );
}

export function InterviewRoomPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const workspace = useQuery({
    queryKey: ["interview-workspace", id],
    queryFn: () => api.getInterviewWorkspace(id),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const state = query.state.data?.latest_workflow?.status;
      if (state === "failed" && (query.state.data?.latest_workflow?.retry_after_seconds ?? 0) > 0) return 3000;
      return state === "queued" || state === "running" ? 1600 : false;
    },
  });
  const chapters = useQuery({ queryKey: ["chapters"], queryFn: api.listChapters });
  const [answer, setAnswer] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const [mobilePane, setMobilePane] = useState<"conversation" | "script">("conversation");
  const [scriptEditing, setScriptEditing] = useState(false);
  const regenerationRequest = useRef<string | null>(null);
  const recorder = useAudioRecorder();

  const session = workspace.data?.session;
  const current = session?.rounds.at(-1);
  const chapter = chapters.data?.find((item) => item.id === session?.chapter_id);
  const chapterScenes = useMemo(
    () => workspace.data?.script?.scenes.filter(
      (scene) => !session?.chapter_id || scene.chapter_id === session.chapter_id,
    ) ?? [],
    [session?.chapter_id, workspace.data?.script?.scenes],
  );
  const chapterScript = chapterScenes[0];

  const submitTurn = useMutation({
    mutationFn: async () => {
      if (!session) throw new ApiError("INTERVIEW_NOT_FOUND", 404);
      const pendingFiles = [...files];
      if (recorder.audioBlob) {
        const extension = recorder.audioBlob.type.includes("ogg") ? "ogg" : "webm";
        pendingFiles.push(new File(
          [recorder.audioBlob],
          `interview-${Date.now()}.${extension}`,
          { type: recorder.audioBlob.type || "audio/webm" },
        ));
      }
      const assets = [];
      for (const file of pendingFiles) {
        const kind = fileKind(file);
        if (!kind) throw new ApiError("EVIDENCE_TYPE_UNSUPPORTED", 415);
        assets.push(await api.uploadEvidence({
          subjectId: session.subject_id,
          interviewSessionId: id,
          kind,
          consentScope: "private",
          file,
        }));
      }
      return api.createInterviewTurn(id, {
        round_id: current && !current.answer_text ? current.id : undefined,
        answer_text: answer.trim() || undefined,
        asset_ids: assets.map((item) => item.id),
        idempotency_key: crypto.randomUUID(),
      });
    },
    onSuccess: async () => {
      setAnswer("");
      setFiles([]);
      setFileError(null);
      recorder.clear();
      await queryClient.invalidateQueries({ queryKey: ["interview-workspace", id] });
      await queryClient.invalidateQueries({ queryKey: ["interviews"] });
    },
  });

  const retryWorkflow = useMutation({
    mutationFn: (jobId: string) => api.retryJob(jobId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["interview-workspace", id] });
    },
  });

  const regenerate = useMutation({
    mutationFn: () => {
      regenerationRequest.current ??= crypto.randomUUID();
      return api.createInterviewTurn(id, {
        action: "regenerate_script", asset_ids: [], idempotency_key: regenerationRequest.current,
      });
    },
    onSuccess: () => {
      regenerationRequest.current = null;
      return queryClient.invalidateQueries({ queryKey: ["interview-workspace", id] });
    },
  });

  function selectFiles(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []);
    setFileError(null);
    try {
      for (const file of picked) {
        const kind = fileKind(file);
        if (!kind) throw new ApiError("EVIDENCE_TYPE_UNSUPPORTED", 415);
        if (file.size > EVIDENCE_LIMITS[kind].bytes) {
          throw new ApiError("EVIDENCE_FILE_TOO_LARGE", 413, {
            kind,
            limit_bytes: EVIDENCE_LIMITS[kind].bytes,
          });
        }
      }
      setFiles((currentFiles) => [...currentFiles, ...picked].slice(0, 12));
    } catch (error) {
      setFileError(errorMessage(error));
    }
    event.target.value = "";
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (scriptEditing || regenerate.isPending || recorder.isRecording || submitTurn.isPending || retryWorkflow.isPending || workspace.data?.latest_workflow &&
      ["queued", "running"].includes(workspace.data.latest_workflow.status)) return;
    if (answer.trim() || recorder.audioBlob || files.length) submitTurn.mutate();
  }

  if (workspace.isPending || workspace.isError || chapters.isPending || chapters.isError) {
    return (
      <div className="page">
        <QueryState queries={[workspace, chapters]} loadingText="正在打开采访工作台……" />
      </div>
    );
  }
  if (!session) return null;

  const visibleRounds = session.rounds.filter((round) => (
    Boolean(round.answer_text) || round.id === current?.id
  ));
  const workflow = workspace.data.latest_workflow;
  const workflowRunning = workflow?.status === "queued" || workflow?.status === "running";
  const workflowError = workflow?.status === "failed" && workflow.error_code
    ? new ApiError(workflow.error_code, 500)
    : null;
  const retryAllowed = workflow?.retry_allowed !== false;
  const retryCooling = (workflow?.retry_after_seconds ?? 0) > 0;
  const scriptSynchronized = workflow?.status === "completed" || workflow?.script_brief?.followup_ready === true;
  const scriptStatus = workflowRunning ? "持续优化中" : scriptSynchronized ? "已同步" : "最新内容尚未同步";

  return (
    <div className="page interview-room interview-workspace-page">
      <div className="interview-mobile-tabs" role="tablist" aria-label="采访工作台">
        <button role="tab" aria-selected={mobilePane === "conversation"} className={mobilePane === "conversation" ? "active" : ""} onClick={() => setMobilePane("conversation")}>采访</button>
        <button role="tab" aria-selected={mobilePane === "script"} className={mobilePane === "script" ? "active" : ""} onClick={() => setMobilePane("script")}>
          剧本 {workflowRunning && <span />}
        </button>
      </div>

      <ErrorNotice error={submitTurn.error || retryWorkflow.error || regenerate.error || workflowError} />
      {workflowError && workflow?.job_id && (
        <div className="interview-retry-action">
          <button
            className="button secondary small"
            disabled={retryWorkflow.isPending || submitTurn.isPending || !retryAllowed || retryCooling}
            onClick={() => retryWorkflow.mutate(workflow.job_id!)}
          >
            <RefreshCw size={15} />
            {retryWorkflow.isPending ? "正在重新提交" : !retryAllowed ? "已达重试上限" : retryCooling ? "稍后可重试" : "重新整理"}
          </button>
          {!retryAllowed && <span>本轮重试已停止，请联系管理员排查。回答和已有剧本均已保留。</span>}
        </div>
      )}
      <main className="live-interview-layout">
        <section className={`conversation-pane ${mobilePane !== "conversation" ? "mobile-hidden" : ""}`} aria-label="采访记录">
          <div className="pane-heading">
            <div><span>采访记录</span><h1>{chapter?.title ?? "自由采访"}</h1></div>
            <small>{visibleRounds.filter((item) => item.answer_text).length} 次回答</small>
          </div>
          <div className="conversation">
            {visibleRounds.map((round) => (
              <div key={round.id} className="conversation-turn">
                {round.question_text && <div className="question-bubble"><span className="ai-avatar">岁</span><p>{round.question_text}</p></div>}
                {round.answer_text && <div className="answer-bubble"><p>{round.answer_text}</p><Check size={15} /></div>}
              </div>
            ))}
            {workspace.data.assets.length > 0 && (
              <div className="chat-assets-history" aria-label="本章已上传素材">
                <strong>本章素材</strong>
                {workspace.data.assets.map((asset) => <Attachment key={asset.id} asset={asset} />)}
              </div>
            )}
          </div>

            <form className="answer-composer" onSubmit={onSubmit}>
              {recorder.audioUrl && (
                <div className="recording-preview">
                  <audio controls src={recorder.audioUrl} />
                  <button type="button" className="icon-button" title="删除录音" aria-label="删除录音" onClick={recorder.clear}><Trash2 size={17} /></button>
                </div>
              )}
              {files.length > 0 && (
                <div className="pending-attachments">
                  {files.map((file, index) => {
                    const kind = fileKind(file) ?? "document";
                    const Icon = kindIcon[kind];
                    return (
                      <div key={`${file.name}-${file.lastModified}`}>
                        <Icon size={16} /><span>{file.name}</span>
                        <button type="button" title="移除素材" aria-label={`移除素材 ${file.name}`} onClick={() => setFiles((items) => items.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={14} /></button>
                      </div>
                    );
                  })}
                </div>
              )}
              <label className="sr-only" htmlFor="interview-answer">说说这段往事</label>
              <textarea id="interview-answer" value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="说说这段往事……" rows={3} disabled={submitTurn.isPending} />
              <div className="composer-actions">
                <label className="composer-tool attachment-button" title={EVIDENCE_LIMIT_SUMMARY}>
                  <Paperclip size={17} /> 添加素材
                  <input className="sr-only" type="file" multiple accept="image/*,audio/*,video/*,.pdf,.txt,.md" onChange={selectFiles} disabled={submitTurn.isPending} />
                </label>
                <button type="button" className={`composer-tool ${recorder.isRecording ? "recording" : ""}`} disabled={submitTurn.isPending} aria-pressed={recorder.isRecording} onClick={() => recorder.isRecording ? recorder.stop() : recorder.start()}>
                  {recorder.isRecording ? <><Square size={16} /> 停止录音</> : <><Mic2 size={17} /> {recorder.audioUrl ? "重新录制" : "录制原声"}</>}
                </button>
                <button className="composer-send" aria-label={submitTurn.isPending || workflowRunning ? "正在整理" : "发送并更新剧本"} title={scriptEditing ? "请先保存或取消剧本修改" : recorder.isRecording ? "请先停止录音" : submitTurn.isPending || workflowRunning ? "正在整理" : "发送并更新剧本"} disabled={scriptEditing || regenerate.isPending || (!answer.trim() && !recorder.audioBlob && !files.length) || recorder.isRecording || submitTurn.isPending || retryWorkflow.isPending || workflowRunning}>
                  {submitTurn.isPending || workflowRunning ? <LoaderCircle size={20} className="composer-spinner" /> : <ArrowUp size={21} />}
                  <span>发送</span>
                </button>
              </div>
              {(fileError || recorder.error) && <p className="form-error">{fileError || recorder.error}</p>}
            </form>
        </section>

        <aside className="workflow-status-rail" aria-label="实时整理状态">
          <span className={workflowRunning ? "running" : workflow?.status === "completed" ? "done" : ""}>
            {workflowRunning ? <LoaderCircle size={16} /> : <CheckCircle2 size={16} />}
          </span>
          <div />
          <small>{workflowRunning ? "正在整理" : scriptSynchronized ? "已经同步" : workflowError ? "尚未同步" : "等待内容"}</small>
        </aside>

        <section className={`live-script-pane ${mobilePane !== "script" ? "mobile-hidden" : ""}`} aria-label="本章实时剧本">
          <div className="pane-heading script-pane-heading">
            <div><span>LIVE SCRIPT</span><h2>{chapter?.title ?? "本章剧本"}</h2></div>
            <div className="script-pane-actions">{chapterScript && <small>{scriptStatus}</small>}
              <button className="icon-button" title="重新生成本章剧本" aria-label="重新生成本章剧本" disabled={scriptEditing || regenerate.isPending || workflowRunning || submitTurn.isPending || retryWorkflow.isPending} onClick={() => regenerate.mutate()}><RefreshCw size={18} /></button>
            </div>
          </div>
          <div className="live-script-scroll" tabIndex={0} aria-label="剧本内容滚动区">
          {workflowRunning && (
            <div className="script-updating"><LoaderCircle size={18} /><div><strong>采访 AI 正在整理</strong><span>识别事实、检查缺口并同步更新本章。</span></div></div>
          )}
          {!chapterScript ? (
            <div className="live-script-empty">
              <BookOpenText size={31} />
              <h3>剧本会从第一段讲述开始</h3>
            </div>
          ) : (
            <article className="live-manuscript">
              <section>
                <EditableScript key={chapterScript.id} scene={chapterScript} project={workspace.data.script!} disabled={workflowRunning || regenerate.isPending || submitTurn.isPending} onEditingChange={setScriptEditing} />
                <footer><span>{chapterScript.duration_seconds} 秒</span><span>{chapterScript.source_claim_ids.length} 条来源</span></footer>
              </section>
            </article>
          )}
          </div>
        </section>
      </main>
    </div>
  );
}
