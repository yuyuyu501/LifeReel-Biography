import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronDown, FileText, Info, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { booksApi } from "../api/books";
import { ErrorNotice, QueryState } from "./QueryState";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";

export function BookScriptGenerator({
  subjectId,
  disabled,
  open,
  onOpenChange,
  onGenerated,
}: {
  subjectId: string;
  disabled: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
    <details
      id="book-script-generator"
      className="book-script-generator"
      open={open}
      onToggle={(event) => onOpenChange(event.currentTarget.open)}
    >
      <summary>
        <span className="studio-generator-icon">
          <FileText size={24} aria-hidden="true" />
        </span>
        <span className="studio-generator-title">
          <strong>从书稿生成剧本与分镜</strong>
          <span>选择已保存的书稿版本</span>
        </span>
        <ChevronDown
          className="studio-generator-chevron"
          size={18}
          aria-hidden="true"
        />
      </summary>
      <div className="studio-generator-body">
        <div className="studio-book-selection">
          <h2>选择书稿版本</h2>
          <QueryState queries={[books]} loadingText="正在读取书稿……" />
          <div className="studio-book-list" role="group" aria-label="书稿版本">
            {chapters.map(({ book, chapter }) => (
              <label
                className={`studio-book-option${chapter.current && chosen.includes(chapter.current.id) ? " is-selected" : ""}`}
                key={chapter.id}
              >
                <input
                  type="checkbox"
                  disabled={
                    disabled ||
                    generate.isPending ||
                    !chapter.current ||
                    chapter.stale
                  }
                  checked={
                    !!chapter.current && chosen.includes(chapter.current.id)
                  }
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
                <span className="studio-book-option-copy">
                  <strong>
                    {book.title} · {chapter.current?.title || chapter.title}
                  </strong>
                  <small>
                    {chapter.stale
                      ? "来源已更正，请先更新书稿"
                      : chapter.current
                        ? `保存版本 ${chapter.current.version_number} · ${new Date(chapter.current.created_at).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })}`
                        : "尚未成稿"}
                  </small>
                </span>
              </label>
            ))}
            {!chapters.some(({ chapter }) => chapter.current) && (
              <p className="studio-book-empty">
                还没有保存的书稿。
                <Link to={`/books?subject=${subjectId}`}>前往写书</Link>
              </p>
            )}
          </div>
          <p className="studio-book-count">
            共 {allowed.size} 个可用版本，已选择 {chosen.length} 个
          </p>
        </div>
        <div className="studio-adaptation">
          <div className="studio-duration">
            <label htmlFor="studio-adaptation-duration">目标时长</label>
            <select
              id="studio-adaptation-duration"
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
          </div>
          <div className="studio-instructions">
            <label htmlFor="studio-adaptation-instructions">
              改编要求（可选）
            </label>
            <span className="studio-instructions-input">
              <Textarea
                id="studio-adaptation-instructions"
                disabled={generate.isPending}
                value={instructions}
                maxLength={4000}
                placeholder="例如：只改编那段工作经历；某个人物不露脸；沿用已确认的人物参考。"
                onChange={(e) => {
                  edited();
                  setInstructions(e.target.value);
                }}
              />
              <span className="studio-instructions-count" aria-hidden="true">
                {instructions.length}/4000
              </span>
            </span>
          </div>
          <p className="studio-billing-note">
            <Info size={14} aria-hidden="true" />
            AI 改编沿用文本模型计费规则；生成图片和视频会在后续操作中分别计费。
          </p>
          <ErrorNotice error={generate.error} />
          <Button
            className="studio-adapt-button"
            disabled={disabled || generate.isPending || !chosen.length}
            onClick={() => generate.mutate()}
          >
            <Sparkles size={16} aria-hidden="true" />
            {generate.isPending ? "正在规划剧情与分镜……" : "生成剧本与分镜"}
          </Button>
        </div>
      </div>
    </details>
  );
}
