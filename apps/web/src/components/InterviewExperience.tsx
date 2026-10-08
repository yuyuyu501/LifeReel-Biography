import { useMutation } from "@tanstack/react-query";
import type {
  Chapter,
  InterviewRound,
  InterviewSession,
  InterviewWorkspace,
} from "@lifereel/contracts";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { errorMessage } from "../api/errors";
import { Button } from "./ui/button";

export function AnswerHistory({ round }: { round: InterviewRound }) {
  if (!round.answer_revisions?.length) return null;
  return (
    <div className="answer-revision">
      <details>
        <summary>查看历史原文</summary>
        {round.answer_revisions.map((item) => (
          <p key={item.version}>
            <small>第 {item.version} 版</small> {item.text}
          </p>
        ))}
      </details>
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
  organizing_profile: "正在填写资料表、整理更正和可写内容",
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
          可以离开页面，后台会继续处理。
        </small>
      )}
    </div>
  );
}
