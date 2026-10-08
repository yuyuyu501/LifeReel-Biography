import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { booksApi, type Book } from "../api/books";
import { profilesApi } from "../api/profiles";
import { ErrorNotice, QueryState } from "./QueryState";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

export function BookDirectoryEditor({
  book,
  disabled,
}: {
  book: Book;
  disabled: boolean;
}) {
  const cache = useQueryClient();
  const [draft, setDraft] = useState<{
    expected_version: number;
    title: string;
    chapters: {
      id?: string;
      title: string;
      source_entry_ids: string[];
    }[];
  } | null>(null);
  const profile = useQuery({
    queryKey: ["life-profile", book.subject_id],
    queryFn: () => profilesApi.subject(book.subject_id),
    enabled: !!draft,
  });
  const save = useMutation({
    mutationFn: () => booksApi.directory(book.id, draft!),
    onSuccess: async (updated) => {
      setDraft(null);
      cache.setQueryData(["book", book.id], updated);
      await cache.invalidateQueries({ queryKey: ["books"] });
    },
  });
  const available =
    profile.data?.entries.filter(
      (e) =>
        e.state === "filled" &&
        !["pending", "disputed"].includes(e.certainty) &&
        e.use_scope !== "internal",
    ) || [];
  function move(index: number, delta: number) {
    if (!draft || index + delta < 0 || index + delta >= draft.chapters.length)
      return;
    const rows = [...draft.chapters];
    [rows[index], rows[index + delta]] = [rows[index + delta], rows[index]];
    setDraft({ ...draft, chapters: rows });
  }
  if (!draft)
    return (
      <Button
        variant="outline"
        disabled={disabled}
        onClick={() => {
          save.reset();
          setDraft({
            expected_version: book.directory_version || 1,
            title: book.title,
            chapters: book.chapters.map((ch) => ({
              id: ch.id,
              title: ch.title,
              source_entry_ids: ch.source_entry_ids || [],
            })),
          });
        }}
      >
        编辑目录与选材
      </Button>
    );
  return (
    <form
      className="book-directory-editor"
      aria-label="编辑书籍目录"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <h2>书籍目录与选材</h2>
      <p>
        目录独立于采访。每章选择资料条目，生成约1000字正文；移除章节会保留历史稿件。
      </p>
      <label>
        书名
        <Input
          value={draft.title}
          onChange={(e) => setDraft({ ...draft, title: e.target.value })}
          required
        />
      </label>
      <QueryState queries={[profile]} />
      {draft.chapters.map((chapter, index) => (
        <section key={chapter.id || index}>
          <label>
            第 {index + 1} 章标题
            <Input
              value={chapter.title}
              required
              onChange={(e) =>
                setDraft({
                  ...draft,
                  chapters: draft.chapters.map((ch, i) =>
                    i === index ? { ...ch, title: e.target.value } : ch,
                  ),
                })
              }
            />
          </label>
          <div className="writing-buttons">
            <Button
              type="button"
              variant="ghost"
              onClick={() => move(index, -1)}
              disabled={!index}
            >
              上移
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => move(index, 1)}
              disabled={index === draft.chapters.length - 1}
            >
              下移
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={draft.chapters.length === 1}
              onClick={() =>
                setDraft({
                  ...draft,
                  chapters: draft.chapters.filter((_, i) => i !== index),
                })
              }
            >
              移出目录
            </Button>
          </div>
          <details>
            <summary>
              本章资料 · 已选择 {chapter.source_entry_ids.length} 条
            </summary>
            {available.map((entry) => {
              const label = profile.data?.fields.find(
                (f) => f.key === entry.field_key,
              )?.label;
              const text =
                typeof entry.value === "string"
                  ? entry.value
                  : String(
                      (entry.value as Record<string, unknown>).title ||
                        (entry.value as Record<string, unknown>).what ||
                        label ||
                        "资料",
                    );
              return (
                <label key={entry.id}>
                  <input
                    type="checkbox"
                    checked={chapter.source_entry_ids.includes(entry.id)}
                    onChange={(e) => {
                      const ids = e.target.checked
                        ? [...chapter.source_entry_ids, entry.id]
                        : chapter.source_entry_ids.filter(
                            (id) => id !== entry.id,
                          );
                      setDraft({
                        ...draft,
                        chapters: draft.chapters.map((ch, i) =>
                          i === index ? { ...ch, source_entry_ids: ids } : ch,
                        ),
                      });
                    }}
                  />
                  {label} · {text.slice(0, 100)}
                </label>
              );
            })}
            {!available.length && (
              <p>还没有可用于作品的资料，请先填写资料表或继续采访。</p>
            )}
          </details>
        </section>
      ))}
      {!!book.archived_chapters?.length && (
        <details>
          <summary>已移出目录的历史章节</summary>
          {book.archived_chapters
            .filter((ch) => !draft.chapters.some((c) => c.id === ch.id))
            .map((ch) => (
              <Button
                type="button"
                key={ch.id}
                variant="outline"
                onClick={() =>
                  setDraft({
                    ...draft,
                    chapters: [
                      ...draft.chapters,
                      {
                        id: ch.id,
                        title: ch.title,
                        source_entry_ids: ch.source_entry_ids || [],
                      },
                    ],
                  })
                }
              >
                恢复：{ch.title}
              </Button>
            ))}
        </details>
      )}
      <ErrorNotice error={save.error} />
      <div className="writing-buttons">
        <Button
          type="button"
          variant="outline"
          disabled={draft.chapters.length >= 40}
          onClick={() =>
            setDraft({
              ...draft,
              chapters: [
                ...draft.chapters,
                { title: "新的经历", source_entry_ids: [] },
              ],
            })
          }
        >
          添加书章
        </Button>
        <Button disabled={save.isPending || !profile.data}>保存目录</Button>
        <Button
          type="button"
          variant="outline"
          disabled={save.isPending}
          onClick={() => setDraft(null)}
        >
          取消
        </Button>
      </div>
    </form>
  );
}
