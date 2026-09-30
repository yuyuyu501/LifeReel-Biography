import { useMutation, useQueryClient } from "@tanstack/react-query";
import type {
  Chapter,
  InterviewRound,
  InterviewSession,
  InterviewWorkspace,
} from "@lifereel/contracts";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";

export function AnswerRevision({
  round,
  sessionId,
  disabled,
  onEditingChange,
}: {
  round: InterviewRound;
  sessionId: string;
  disabled: boolean;
  onEditingChange: (editing: boolean) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(round.answer_text ?? "");
  const request = useRef<{ text: string; key: string } | null>(null);
  const cache = useQueryClient();
  const revision = useMutation({
    mutationFn: () => {
      if (request.current?.text !== text)
        request.current = { text, key: crypto.randomUUID() };
      return api.createInterviewTurn(sessionId, {
        action: "revise_answer",
        round_id: round.id,
        expected_version: round.answer_version ?? 1,
        answer_text: text,
        asset_ids: [],
        idempotency_key: request.current.key,
      });
    },
    onSuccess: async () => {
      setEditing(false);
      onEditingChange(false);
      request.current = null;
      await cache.invalidateQueries({
        queryKey: ["interview-workspace", sessionId],
      });
      await cache.invalidateQueries({ queryKey: ["interviews"] });
      await cache.invalidateQueries({ queryKey: ["scripts"] });
      await Promise.all(
        [
          "memories",
          "memory-overview",
          "memory-graph",
          "memory-timeline",
          "memory-conflicts",
        ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
      );
    },
  });
  return (
    <div className="answer-revision">
      {editing ? (
        <div className="answer-editor">
          <label htmlFor={"revision-" + round.id}>修改这条回答</label>
          <Textarea
            id={"revision-" + round.id}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={revision.isPending}
          />
          <small>
            请保留这条回答中仍正确的内容。原文会保留，记忆和本章剧本将按修订重新整理；已有视频不会自动重做。
          </small>
          <div className="experience-actions">
            <Button
              type="button"
              disabled={
                disabled ||
                revision.isPending ||
                !text.trim() ||
                text.trim() === round.answer_text
              }
              onClick={() => revision.mutate()}
            >
              {revision.isPending ? "正在保存修订" : "保存并重新整理"}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={revision.isPending}
              onClick={() => {
                setEditing(false);
                onEditingChange(false);
                revision.reset();
              }}
            >
              取消修改
            </Button>
          </div>
          {revision.isError && (
            <p role="alert">{errorMessage(revision.error)}</p>
          )}
        </div>
      ) : (
        <Button
          type="button"
          variant="link"
          size="sm"
          disabled={disabled}
          aria-label={"修改第" + round.round_index + "条回答"}
          onClick={() => {
            setText(round.answer_text ?? "");
            setEditing(true);
            onEditingChange(true);
            revision.reset();
          }}
        >
          修改回答
        </Button>
      )}
      {Boolean(round.answer_revisions?.length) && (
        <details>
          <summary>已修订 · 查看原文</summary>
          {round.answer_revisions?.map((item) => (
            <p key={item.version}>
              <small>第 {item.version} 版</small> {item.text}
            </p>
          ))}
        </details>
      )}
    </div>
  );
}

export function ChapterNavigation({
  chapters,
  session,
  disabled,
  canLeave,
}: {
  chapters: Chapter[];
  session: InterviewSession;
  disabled: boolean;
  canLeave: () => boolean;
}) {
  const navigate = useNavigate();
  const ordered = [...chapters].sort((a, b) => a.order_index - b.order_index);
  const index = ordered.findIndex((c) => c.id === session.chapter_id);
  const start = useMutation({
    mutationFn: (chapterId: string) =>
      api.startInterview({
        subject_id: session.subject_id,
        chapter_id: chapterId,
      }),
    onSuccess: (result) => navigate("/interviews/" + result.id),
  });
  function open(chapterId?: string) {
    if (chapterId && chapterId !== session.chapter_id && canLeave())
      start.mutate(chapterId);
  }
  return (
    <nav className="chapter-navigation" aria-label="采访章节导航">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || start.isPending || index <= 0}
        onClick={() => open(ordered[index - 1]?.id)}
      >
        上一章
      </Button>
      <select
        aria-label="章节目录"
        value={session.chapter_id ?? ""}
        disabled={disabled || start.isPending}
        onChange={(e) => open(e.target.value)}
      >
        {index < 0 && <option value="">自由采访</option>}
        {ordered.map((c) => (
          <option key={c.id} value={c.id}>
            {c.order_index}. {c.title}
          </option>
        ))}
      </select>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={
          disabled ||
          start.isPending ||
          index < 0 ||
          index >= ordered.length - 1
        }
        onClick={() => open(ordered[index + 1]?.id)}
      >
        下一章
      </Button>
      {start.isError && <p role="alert">{errorMessage(start.error)}</p>}
    </nav>
  );
}

const STAGES: Record<string, string> = {
  queued: "已保存，正在排队",
  analyzing_materials: "正在读取照片或录音",
  updating_memory: "正在整理记忆",
  assessing_chapter: "正在梳理本章线索",
  preparing_reply: "正在准备回应",
  updating_script: "正在更新本章剧本",
  completed: "本轮整理完成，可以继续补充",
  failed: "整理暂未完成，已保存的回答仍然保留",
};

export function InterviewProgress({
  workspace,
}: {
  workspace: InterviewWorkspace;
}) {
  const [now, setNow] = useState(() => Date.now());
  const workflow = workspace.latest_workflow;
  const running =
    workflow?.status === "queued" || workflow?.status === "running";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  if (!workflow) return null;
  const started = Date.parse(workflow.created_at);
  const elapsed =
    running && Number.isFinite(started)
      ? Math.max(0, Math.floor((now - started) / 1000))
      : (workspace.progress?.elapsed_seconds ?? 0);
  const estimate = workspace.progress?.estimated_seconds;
  const stage =
    workspace.progress?.stage ??
    String(workflow.script_brief?.stage ?? workflow.status);
  return (
    <div className="interview-progress">
      <p role="status" aria-live="polite">
        {STAGES[stage] ?? "正在整理"}
        {running && workflow.next_question ? "；采访回应已就绪" : ""}
      </p>
      {running && (
        <small>
          已等待 {elapsed} 秒。
          {estimate
            ? "类似任务总耗时通常为 " +
              estimate[0] +
              "–" +
              estimate[1] +
              " 秒，实际时间可能变化。"
            : "当前同类样本不足，暂不提供预计时间。"}
          可以切换章节，后台会继续处理。
        </small>
      )}
    </div>
  );
}
