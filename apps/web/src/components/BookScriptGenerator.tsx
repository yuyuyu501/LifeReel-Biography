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
  const [instructions, setInstructions] = useState("");
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const book = books.data?.find((item) => item.subject_id === subjectId);
  const saved = book?.chapters.filter((chapter) => chapter.current) ?? [];
  const stale = saved.filter((chapter) => chapter.stale).length;
  const generate = useMutation({
    mutationFn: () =>
      api.generateScript({
        subject_id: subjectId,
        book_id: book!.id,
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
          <span>整本书稿</span>
        </span>
        <ChevronDown
          className="studio-generator-chevron"
          size={18}
          aria-hidden="true"
        />
      </summary>
      <div className="studio-generator-body">
        <div className="studio-book-selection">
          <QueryState queries={[books]} loadingText="正在读取书稿……" />
          {book && (
            <>
              <h2 className="studio-book-title">{book.title}</h2>
              <p className="studio-book-count">
                已成稿 {saved.length} / {book.chapters.length} 章
              </p>
              {stale > 0 && (
                <p className="studio-book-empty" role="status">
                  {stale} 章来源已更正，请先更新书稿。
                  <Link to={`/books?subject=${subjectId}`}>前往写书</Link>
                </p>
              )}
            </>
          )}
          {!books.isPending && !books.isError && !saved.length && (
            <p className="studio-book-empty">
              还没有保存的书稿。
              <Link to={`/books?subject=${subjectId}`}>前往写书</Link>
            </p>
          )}
        </div>
        <div className="studio-adaptation">
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
                placeholder="例如：保留家乡生活的细节；某个人物不露脸；沿用已确认的人物参考。"
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
            disabled={
              disabled ||
              generate.isPending ||
              books.isPending ||
              books.isError ||
              !saved.length ||
              stale > 0
            }
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
