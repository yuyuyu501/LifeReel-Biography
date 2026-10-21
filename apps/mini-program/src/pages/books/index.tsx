import { useEffect, useState } from "react";
import {
  Button,
  Checkbox,
  CheckboxGroup,
  Input,
  Label,
  Text,
  Textarea,
  View,
} from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type { Book, BookChapter, LifeProfile } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { newRequestId } from "../../shared/uuid";
import { PageFrame } from "../../shared/PageFrame";
import { Icon } from "../../shared/Icon";

export default function BooksPage() {
  const subjectId = getCurrentInstance().router?.params.subjectId || "";
  const [book, setBook] = useState<Book | null>(null);
  const [profile, setProfile] = useState<LifeProfile | null>(null);
  const [directory, setDirectory] = useState<Book["chapters"] | null>(null);
  const [draft, setDraft] = useState<{
    chapter: BookChapter;
    title: string;
    body: string;
  } | null>(null);
  const [confirmSources, setConfirmSources] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<string[]>([]);
  const working = !!book?.chapters.some((c) =>
    ["queued", "running"].includes(c.status),
  );
  useEffect(() => {
    if (!subjectId) {
      setError("请先选择人物");
      return;
    }
    Promise.all([miniApi.createBook(subjectId), miniApi.profile(subjectId)])
      .then(([value, facts]) => {
        setBook(value);
        setProfile(facts);
      })
      .catch((e) => setError(e.message));
  }, [subjectId]);
  useEffect(() => {
    if (!working || !book) return;
    const timer = setInterval(
      () =>
        miniApi
          .book(book.id)
          .then(setBook)
          .catch((e) => setError(e.message)),
      2500,
    );
    return () => clearInterval(timer);
  }, [working, book?.id]);
  async function generate(chapter?: BookChapter) {
    if (!book || busy || directory || draft) return;
    setBusy(true);
    setError("");
    try {
      await miniApi.writeBook(book.id, {
        idempotency_key: newRequestId(),
        overwrite: !!chapter,
        chapter_ids: chapter ? [chapter.chapter_id] : undefined,
        expected_versions: chapter
          ? { [chapter.chapter_id]: chapter.version_number }
          : undefined,
      });
      setBook(await miniApi.book(book.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成未完成");
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!book || !draft) return;
    setBusy(true);
    setError("");
    try {
      const facts = confirmSources ? await miniApi.profile(subjectId) : null;
      setBook(
        await miniApi.editBookChapter(book.id, draft.chapter.chapter_id, {
          expected_version: draft.chapter.version_number,
          title: draft.title,
          body: draft.body,
          confirm_profile_version: facts?.version_number,
        }),
      );
      setDraft(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存未完成，草稿仍保留");
    } finally {
      setBusy(false);
    }
  }
  async function saveDirectory() {
    if (!book || !directory) return;
    setBusy(true);
    setError("");
    try {
      setBook(
        await miniApi.bookDirectory(book.id, {
          expected_version: book.directory_version,
          title: book.title,
          chapters: directory.map((c) => ({
            id: c.id || undefined,
            title: c.title,
            source_entry_ids: c.source_entry_ids,
          })),
        }),
      );
      setDirectory(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "目录保存失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <PageFrame
      title="人生之书"
      subtitle="把走过的日子，写成一本书。"
      active="books"
      subjectId={subjectId}
      locked={busy || !!draft || !!directory}
    >
      {error && <Text className="error">{error}</Text>}
      {book && (
        <>
          <View className="book-summary">
            <Text className="eyebrow">我的书稿</Text>
            <Text className="list-title">{book.title}</Text>
            <Text className="hint">
              {book.chapters.length} 章 ·{" "}
              {book.chapters.filter((c) => c.current).length} 章已成稿
            </Text>
          </View>
          <View className="action-row">
            <Button
              className="primary-button"
              loading={busy && !draft && !directory}
              disabled={busy || working || !!draft || !!directory}
              onClick={() => generate()}
            >
              <Icon name="book" tone="white" />
              补齐未成稿章节
            </Button>
            <Button
              disabled={busy || working || !!draft || !!directory}
              onClick={() => setDirectory(book.chapters.map((c) => ({ ...c })))}
            >
              <Icon name="edit" />
              目录与选材
            </Button>
            <Button
              disabled={busy || !!draft || !!directory}
              onClick={() =>
                Taro.navigateTo({
                  url: `/pages/profile/index?subjectId=${subjectId}`,
                })
              }
            >
              资料表
            </Button>
            <Button
              disabled={busy || !!draft || !!directory}
              onClick={() =>
                Taro.navigateTo({
                  url: `/pages/production/index?subjectId=${subjectId}&tab=script`,
                })
              }
            >
              书稿改编影像
            </Button>
          </View>
          {directory && (
            <View className="section directory-editor">
              <Text className="section-title">目录与选材</Text>
              {directory.map((ch, index) => (
                <View className="card" key={ch.id || index}>
                  <Text className="caption">
                    第 {index + 1} 章 · {ch.source_entry_ids.length} 条素材
                  </Text>
                  <Input
                    className="input"
                    value={ch.title}
                    onInput={(e) =>
                      setDirectory(
                        directory.map((c, i) =>
                          i === index ? { ...c, title: e.detail.value } : c,
                        ),
                      )
                    }
                  />
                  <View className="action-row">
                    <Button
                      disabled={index === 0}
                      onClick={() => {
                        const rows = [...directory];
                        [rows[index - 1], rows[index]] = [
                          rows[index],
                          rows[index - 1],
                        ];
                        setDirectory(rows);
                      }}
                    >
                      上移
                    </Button>
                    <Button
                      disabled={index === directory.length - 1}
                      onClick={() => {
                        const rows = [...directory];
                        [rows[index + 1], rows[index]] = [
                          rows[index],
                          rows[index + 1],
                        ];
                        setDirectory(rows);
                      }}
                    >
                      下移
                    </Button>
                    <Button
                      disabled={directory.length === 1}
                      onClick={() =>
                        setDirectory(directory.filter((_, i) => i !== index))
                      }
                    >
                      移出目录
                    </Button>
                  </View>
                  <CheckboxGroup
                    onChange={(e) =>
                      setDirectory(
                        directory.map((c, i) =>
                          i === index
                            ? { ...c, source_entry_ids: e.detail.value }
                            : c,
                        ),
                      )
                    }
                  >
                    {profile?.entries
                      .filter(
                        (e) =>
                          e.state === "filled" &&
                          e.use_scope !== "internal" &&
                          !["pending", "disputed"].includes(e.certainty),
                      )
                      .map((e) => (
                        <Label key={e.id} className="material-option">
                          <Checkbox
                            value={e.id}
                            checked={ch.source_entry_ids.includes(e.id)}
                            color="#176e62"
                            disabled={busy}
                          />
                          <Text>
                            {
                              profile.fields.find((f) => f.key === e.field_key)
                                ?.label
                            }{" "}
                            ·{" "}
                            {typeof e.value === "string"
                              ? e.value.slice(0, 30)
                              : String(
                                  (e.value as Record<string, unknown>).title ||
                                    "经历",
                                )}
                          </Text>
                        </Label>
                      ))}
                  </CheckboxGroup>
                </View>
              ))}
              <Button
                onClick={() =>
                  setDirectory([
                    ...directory,
                    {
                      id: "",
                      chapter_id: "",
                      title: "新的经历",
                      order_index: directory.length + 1,
                      source_entry_ids: [],
                      version_number: 0,
                      status: "empty",
                      source_count: 0,
                      stale: false,
                      job_id: null,
                      error_code: null,
                      current: null,
                    },
                  ])
                }
              >
                添加书章
              </Button>
              {book.archived_chapters
                ?.filter((ch) => !directory.some((c) => c.id === ch.id))
                .map((ch) => (
                  <Button
                    key={ch.id}
                    onClick={() => setDirectory([...directory, ch])}
                  >
                    恢复：{ch.title}
                  </Button>
                ))}
              <Button
                className="primary-button"
                disabled={busy}
                onClick={saveDirectory}
              >
                保存目录
              </Button>
              <Button disabled={busy} onClick={() => setDirectory(null)}>
                取消
              </Button>
            </View>
          )}
          {draft ? (
            <View className="section">
              <Text className="section-title">编辑书稿</Text>
              <Input
                className="input"
                value={draft.title}
                onInput={(e) => setDraft({ ...draft, title: e.detail.value })}
              />
              <Textarea
                className="textarea"
                maxlength={12000}
                value={draft.body}
                onInput={(e) => setDraft({ ...draft, body: e.detail.value })}
              />
              <CheckboxGroup
                onChange={(e) =>
                  setConfirmSources(e.detail.value.includes("confirmed"))
                }
              >
                <Label className="material-option">
                  <Checkbox
                    value="confirmed"
                    checked={confirmSources}
                    disabled={busy}
                    color="#176e62"
                  />
                  <Text>正文已按当前资料更正</Text>
                </Label>
              </CheckboxGroup>
              <View className="action-row">
                <Button
                  className="primary-button"
                  loading={busy}
                  disabled={busy || !draft.body.trim()}
                  onClick={save}
                >
                  保存书稿版本
                </Button>
              </View>
              <Button disabled={busy} onClick={() => setDraft(null)}>
                取消
              </Button>
            </View>
          ) : (
            book.chapters.map((ch) => (
              <View className="card" key={ch.id}>
                <View className="chapter-heading">
                  <Text className="chapter-number">
                    {String(ch.order_index).padStart(2, "0")}
                  </Text>
                  <View className="chapter-heading-copy">
                    <Text className="section-title">{ch.title}</Text>
                    <Text className="caption">
                      {ch.current
                        ? `${ch.current.word_count} 字 · 第 ${ch.version_number} 版`
                        : "尚未成稿"}
                    </Text>
                  </View>
                </View>
                {ch.stale && (
                  <Text className="error">
                    来源有更正，请更新书稿后再改编。
                  </Text>
                )}
                {ch.error_code && (
                  <Text className="error">
                    本章未完成：{ch.error_code}，旧稿仍保留。
                  </Text>
                )}
                {ch.current && (
                  <Text
                    className={`manuscript ${expanded.includes(ch.id) ? "" : "is-collapsed"}`}
                  >
                    {ch.current.body}
                  </Text>
                )}
                {ch.current && (
                  <Button
                    className="text-button"
                    onClick={() =>
                      setExpanded((rows) =>
                        rows.includes(ch.id)
                          ? rows.filter((id) => id !== ch.id)
                          : [...rows, ch.id],
                      )
                    }
                  >
                    {expanded.includes(ch.id) ? "收起正文" : "阅读全文"}
                    <Icon name="down" />
                  </Button>
                )}
                <View className="action-row">
                  <Button
                    disabled={
                      busy || working || !!directory || !ch.source_count
                    }
                    onClick={() => generate(ch)}
                  >
                    {working
                      ? "写作中……"
                      : ch.current
                        ? "重新生成"
                        : "生成本章"}
                  </Button>
                  <Button
                    disabled={busy || working || !!directory}
                    onClick={() => {
                      setConfirmSources(false);
                      setDraft({
                        chapter: ch,
                        title: ch.current?.title || ch.title,
                        body: ch.current?.body || "",
                      });
                    }}
                  >
                    <Icon name="edit" />
                    编辑正文
                  </Button>
                </View>
              </View>
            ))
          )}
        </>
      )}
      {!book && !error && <Text className="empty">正在读取书稿……</Text>}
    </PageFrame>
  );
}
