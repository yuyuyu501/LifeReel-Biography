import { useEffect, useState } from "react";
import { Button, Input, Text, Textarea, View } from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type { Book, BookChapter, LifeProfile } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { newRequestId } from "../../shared/uuid";
import { PreviewNotice } from "../../shared/PreviewNotice";

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
    if (!book) return;
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
    <View className="page">
      <PreviewNotice />
      <Text className="title">人生写书</Text>
      <Text className="hint">
        从资料表选材，每章约1000字，书章可以独立调整。
      </Text>
      {error && <Text className="error">{error}</Text>}
      {book && (
        <>
          <Text className="section-title">{book.title}</Text>
          <View className="action-row">
            <Button
              disabled={busy || working || !!draft || !!directory}
              onClick={() => generate()}
            >
              生成待写章节
            </Button>
            <Button
              disabled={busy || working || !!draft}
              onClick={() => setDirectory(book.chapters.map((c) => ({ ...c })))}
            >
              编辑目录与选材
            </Button>
            <Button
              onClick={() =>
                Taro.navigateTo({
                  url: `/pages/profile/index?subjectId=${subjectId}`,
                })
              }
            >
              资料表
            </Button>
            <Button
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
            <View className="card">
              {directory.map((ch, index) => (
                <View key={ch.id || index}>
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
                  {profile?.entries
                    .filter(
                      (e) =>
                        e.state === "filled" &&
                        e.use_scope !== "internal" &&
                        !["pending", "disputed"].includes(e.certainty),
                    )
                    .map((e) => (
                      <Button
                        key={e.id}
                        className={
                          ch.source_entry_ids.includes(e.id)
                            ? "primary-button"
                            : "secondary-button"
                        }
                        onClick={() =>
                          setDirectory(
                            directory.map((c, i) =>
                              i === index
                                ? {
                                    ...c,
                                    source_entry_ids:
                                      c.source_entry_ids.includes(e.id)
                                        ? c.source_entry_ids.filter(
                                            (id) => id !== e.id,
                                          )
                                        : [...c.source_entry_ids, e.id],
                                  }
                                : c,
                            ),
                          )
                        }
                      >
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
                      </Button>
                    ))}
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
              <Button disabled={busy} onClick={saveDirectory}>
                保存目录
              </Button>
              <Button onClick={() => setDirectory(null)}>取消</Button>
            </View>
          )}
          {draft ? (
            <View className="card">
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
              <Button
                className={
                  confirmSources ? "primary-button" : "secondary-button"
                }
                onClick={() => setConfirmSources(!confirmSources)}
              >
                {confirmSources ? "已确认" : "确认"}正文已按当前资料更正
              </Button>
              <Button disabled={busy || !draft.body.trim()} onClick={save}>
                保存书稿版本
              </Button>
              <Button disabled={busy} onClick={() => setDraft(null)}>
                取消
              </Button>
            </View>
          ) : (
            book.chapters.map((ch) => (
              <View className="card" key={ch.id}>
                <Text className="section-title">
                  {ch.order_index}. {ch.title}
                </Text>
                <Text className="hint">
                  {ch.current
                    ? `${ch.current.word_count} 字 · 第 ${ch.version_number} 版`
                    : "尚未成稿"}
                </Text>
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
                <Text className="list-meta">
                  {ch.current?.body || "可以补充资料生成，或手动写作。"}
                </Text>
                <View className="action-row">
                  <Button
                    disabled={busy || working || !ch.source_count}
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
                    onClick={() =>
                      setDraft({
                        chapter: ch,
                        title: ch.current?.title || ch.title,
                        body: ch.current?.body || "",
                      })
                    }
                  >
                    编辑正文
                  </Button>
                </View>
              </View>
            ))
          )}
        </>
      )}
    </View>
  );
}
