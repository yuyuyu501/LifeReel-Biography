import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { booksApi } from "../api/books";
import { ErrorNotice, QueryState } from "./QueryState";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";

export function BookScriptGenerator({
  subjectId,
  disabled,
  onGenerated,
}: {
  subjectId: string;
  disabled: boolean;
  onGenerated: (id: string) => void;
}) {
  const cache = useQueryClient();
  const books = useQuery({ queryKey: ["books"], queryFn: booksApi.list });
  const [selected, setSelected] = useState<string[]>([]);
  const [duration, setDuration] = useState(45);
  const [instructions, setInstructions] = useState("");
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const chapters = (books.data || [])
    .filter((book) => book.subject_id === subjectId)
    .flatMap((book) => book.chapters.map((chapter) => ({ book, chapter })));
  const allowed = new Set(
    chapters
      .filter(({ chapter }) => chapter.current && !chapter.stale)
      .map(({ chapter }) => chapter.current!.id),
  );
  const chosen = selected.filter((id) => allowed.has(id));
  const generate = useMutation({
    mutationFn: () =>
      api.generateScript({
        subject_id: subjectId,
        book_revision_ids: chosen,
        duration_seconds: duration,
        adaptation_instructions: instructions,
        mode: "multi_chapter",
        audience: "family",
        idempotency_key: requestId,
      }),
    onSuccess: async (project) => {
      await cache.invalidateQueries({ queryKey: ["scripts"] });
      await cache.invalidateQueries({ queryKey: ["wallet"] });
      setRequestId(crypto.randomUUID());
      onGenerated(project.id);
    },
  });
  function edited() {
    setRequestId(crypto.randomUUID());
    generate.reset();
  }
  return (
    <details className="book-script-generator" open={!chapters.length}>
      <summary>从书稿生成剧本与分镜</summary>
      <p>
        选择已保存的书稿版本，先生成可编辑剧本；影像制作在审核剧本后另行启动。
      </p>
      <QueryState queries={[books]} loadingText="正在读取书稿……" />
      {chapters.map(({ book, chapter }) => (
        <label key={chapter.id}>
          <input
            type="checkbox"
            disabled={
              disabled ||
              generate.isPending ||
              !chapter.current ||
              chapter.stale
            }
            checked={!!chapter.current && chosen.includes(chapter.current.id)}
            onChange={(e) => {
              const id = chapter.current!.id;
              edited();
              setSelected(
                e.target.checked
                  ? [...chosen, id]
                  : chosen.filter((k) => k !== id),
              );
            }}
          />
          {book.title} · {chapter.current?.title || chapter.title}
          <small>
            {chapter.stale
              ? "来源已更正，请先更新书稿"
              : chapter.current
                ? `保存版本 ${chapter.current.version_number}`
                : "尚未成稿"}
          </small>
        </label>
      ))}
      {!chapters.some(({ chapter }) => chapter.current) && (
        <p>
          还没有保存的书稿。
          <Link to={`/books?subject=${subjectId}`}>前往写书</Link>
        </p>
      )}
      <label>
        目标时长
        <select
          disabled={generate.isPending}
          value={duration}
          onChange={(e) => {
            edited();
            setDuration(Number(e.target.value));
          }}
        >
          <option value={30}>30 秒</option>
          <option value={45}>45 秒</option>
          <option value={60}>60 秒</option>
        </select>
      </label>
      <label>
        改编要求（可选）
        <Textarea
          disabled={generate.isPending}
          value={instructions}
          maxLength={4000}
          placeholder="例如：只改编那段工作经历；某个人物不露脸；沿用已确认的人物参考。"
          onChange={(e) => {
            edited();
            setInstructions(e.target.value);
          }}
        />
      </label>
      <p>AI 改编沿用文本模型计费规则；生成图片和视频会在后续操作中分别计费。</p>
      <ErrorNotice error={generate.error} />
      <Button
        disabled={disabled || generate.isPending || !chosen.length}
        onClick={() => generate.mutate()}
      >
        {generate.isPending ? "正在规划剧情与分镜……" : "生成剧本与分镜"}
      </Button>
    </details>
  );
}
