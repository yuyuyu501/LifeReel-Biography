import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { BookOpenText, Download, Sparkles } from "lucide-react";
import { api, API_BASE_URL } from "../api/client";
import {
  booksApi,
  type Book,
  type BookChapter,
  type BookGeneration,
} from "../api/books";
import { ERROR_MESSAGES } from "../api/errors";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { ErrorNotice, QueryState } from "../components/QueryState";
import { hasQueryIssue } from "../queryHelpers";

const active = (chapter: BookChapter) =>
  ["queued", "running"].includes(chapter.status);
const statusText: Record<string, string> = {
  queued: "等待写作",
  running: "正在写作",
  completed: "已成稿",
  empty: "未生成",
  failed: "本次生成失败",
  needs_material: "待补充资料",
};

export function BooksPage() {
  const navigate = useNavigate();
  const cache = useQueryClient();
  const people = useQuery({ queryKey: ["persons"], queryFn: api.listPersons });
  const books = useQuery({ queryKey: ["books"], queryFn: booksApi.list });
  const [personId, setPersonId] = useState("");
  const [title, setTitle] = useState("");
  const create = useMutation({
    mutationFn: booksApi.create,
    onSuccess: async (book) => {
      await cache.invalidateQueries({ queryKey: ["books"] });
      navigate("/books/" + book.id);
    },
  });
  if (hasQueryIssue([people, books]))
    return (
      <div className="page">
        <QueryState queries={[people, books]} />
      </div>
    );
  return (
    <div className="page writing-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">把经历写成一本书</span>
          <h1>人生书架</h1>
          <p>
            以真实采访与当前记忆为依据，每章约1000字，慢慢写成一本属于自己的书。
          </p>
        </div>
      </header>
      <form
        className="writing-create"
        onSubmit={(event) => {
          event.preventDefault();
          if (personId && !create.isPending)
            create.mutate({
              subject_id: personId,
              title: title.trim() || undefined,
            });
        }}
      >
        <label>
          选择人物
          <select
            value={personId}
            onChange={(e) => setPersonId(e.target.value)}
            required
          >
            <option value="">请选择一位家人</option>
            {people.data?.map((person) => (
              <option key={person.id} value={person.id}>
                {person.preferred_name || person.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          书名
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={180}
            placeholder="留空时使用人物姓名"
          />
        </label>
        <Button disabled={!personId || create.isPending}>
          <BookOpenText size={17} />
          {create.isPending ? "正在打开……" : "创建或打开书籍"}
        </Button>
        <p>每位人物一本书。创建书籍免费；点击生成后按现有文字模型规则计费。</p>
        <ErrorNotice error={create.error} />
      </form>
      <div className="writing-shelf">
        {books.data?.map((book) => (
          <Link
            className="writing-cover"
            to={"/books/" + book.id}
            key={book.id}
          >
            <BookOpenText size={28} />
            <h2>{book.title}</h2>
            <p>
              {book.chapters.filter((c) => c.current).length} /{" "}
              {book.chapters.length} 章已成稿
            </p>
            <span>
              {book.chapters.reduce(
                (n, c) => n + (c.current?.word_count || 0),
                0,
              )}{" "}
              字 · 打开书稿 →
            </span>
          </Link>
        ))}
        {!books.data?.length && (
          <p className="writing-empty">
            书架还是空的。选择人物，开启第一本人生书。
          </p>
        )}
      </div>
    </div>
  );
}

function WritingPrice() {
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: api.wallet });
  const price = wallet.data?.prices;
  if (!price)
    return (
      <p className="wallet-note">
        生成会调用文字模型并计费。请先在<Link to="/wallet">钱包</Link>
        查看现行价格。
      </p>
    );
  return (
    <p className="wallet-note">
      {price.script_billing_mode === "tokens"
        ? "写书按实际 AI 用量计费，沿用官方标准价的1.5倍；字数或来源检查失败时，已发生的模型用量仍会计费。每章最多尝试两次。"
        : "每章每次成功生成或重写 " +
          (price.script_chapter_cents / 100).toFixed(2) +
          " 元，失败不扣章节费；相同请求重试不重复收费。"}
      <Link to="/wallet">查看钱包</Link>
    </p>
  );
}

export function BookWritingPage() {
  const { bookId = "" } = useParams();
  const cache = useQueryClient();
  const book = useQuery({
    queryKey: ["book", bookId],
    queryFn: () => booksApi.read(bookId),
    refetchInterval: (query) =>
      query.state.data?.chapters.some(active) ? 2500 : false,
  });
  const [selected, setSelected] = useState("");
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState("");
  const request = useRef<{ fingerprint: string; id: string } | null>(null);
  const generate = useMutation({
    mutationFn: (payload: BookGeneration) => booksApi.generate(bookId, payload),
    onSuccess: async (result) => {
      request.current = null;
      setNotice(
        result.job_ids.length
          ? "已安排 " +
              result.job_ids.length +
              " 章写作，可离开页面，稍后回来查看。"
          : "没有安排新任务：章节已是最新稿，或缺少可用资料。请查看目录状态。",
      );
      await cache.invalidateQueries({ queryKey: ["book", bookId] });
      await cache.invalidateQueries({ queryKey: ["books"] });
    },
    onSettled: () => cache.invalidateQueries({ queryKey: ["wallet"] }),
  });
  if (hasQueryIssue([book]))
    return (
      <div className="page">
        <QueryState queries={[book]} />
      </div>
    );
  if (!book.data) return null;
  const data = book.data;
  const chapter =
    data.chapters.find((c) => c.chapter_id === selected) || data.chapters[0];
  const busy = generate.isPending || editing || data.chapters.some(active);
  const completed = data.chapters.filter((c) => c.current).length;
  function submit(one: boolean) {
    if (busy || !chapter) return;
    const payload = {
      ...(one ? { chapter_ids: [chapter.chapter_id], overwrite: true } : {}),
      expected_versions: Object.fromEntries(
        data.chapters.map((c) => [c.chapter_id, c.version_number]),
      ),
    };
    const fingerprint = JSON.stringify(payload);
    if (request.current?.fingerprint !== fingerprint)
      request.current = { fingerprint, id: crypto.randomUUID() };
    generate.mutate({ ...payload, idempotency_key: request.current.id });
  }
  return (
    <div className="page writing-page">
      <Link to="/books" className="writing-back">
        ← 人生书架
      </Link>
      <header className="page-header">
        <div>
          <span className="eyebrow">纪实人生 · 每章约1000字</span>
          <h1>{data.title}</h1>
          <p>
            {completed} / {data.chapters.length} 章已成稿 · 正文共{" "}
            {data.chapters.reduce(
              (n, c) => n + (c.current?.word_count || 0),
              0,
            )}{" "}
            字
          </p>
        </div>
      </header>
      <section className="writing-actions" aria-label="书稿操作">
        <WritingPrice />
        <div className="writing-buttons">
          <Button
            disabled={busy || !data.chapters.some((c) => c.source_count)}
            onClick={() => submit(false)}
          >
            <Sparkles size={16} />
            生成全书待写章节
          </Button>
          <span>仅生成未成稿或资料已更新的章节，缺少资料的章节会跳过。</span>
          {completed > 0 && (
            <>
              <a
                className="writing-export"
                href={
                  API_BASE_URL + "/v1/books/" + bookId + "/export?format=txt"
                }
              >
                <Download size={16} />
                导出 TXT
              </a>
              <a
                className="writing-export"
                href={
                  API_BASE_URL + "/v1/books/" + bookId + "/export?format=md"
                }
              >
                导出 Markdown
              </a>
            </>
          )}
        </div>
        {notice && <p role="status">{notice}</p>}
        <ErrorNotice error={generate.error} />
      </section>
      <section className="book-reading-layout" aria-label="书稿章节">
        <aside className="book-toc">
          <h2>章节目录</h2>
          <div className="book-chapter-list">
            {data.chapters.map((c) => (
              <div
                key={c.id}
                className={c.chapter_id === chapter?.chapter_id ? "active" : ""}
              >
                <button
                  disabled={editing}
                  onClick={() => {
                    setSelected(c.chapter_id);
                    setNotice("");
                  }}
                  aria-current={
                    c.chapter_id === chapter?.chapter_id ? "true" : undefined
                  }
                >
                  <span>{c.order_index}</span>
                  <span>
                    <strong>{c.title}</strong>
                    <small>
                      {statusText[c.status] || c.status}
                      {c.stale ? " · 资料已更新" : ""}
                      {c.current ? " · " + c.current.word_count + "字" : ""}
                    </small>
                  </span>
                </button>
              </div>
            ))}
          </div>
        </aside>
        {chapter && (
          <article className="book-manuscript">
            <header className="manuscript-header">
              <div>
                <span>
                  第 {chapter.order_index} 章 · {chapter.source_count}{" "}
                  条可用记忆
                </span>
                <h2>{chapter.title}</h2>
              </div>
              <Button
                disabled={busy || !chapter.source_count}
                onClick={() => submit(true)}
              >
                {active(chapter)
                  ? "正在写作……"
                  : chapter.current
                    ? "重新生成本章"
                    : "生成本章"}
              </Button>
            </header>
            {chapter.stale && (
              <p className="writing-warning" role="status">
                采访资料已更正或补充。当前稿仍保留原版本，可点击“重新生成本章”同步最新事实。
              </p>
            )}
            {chapter.error_code && (
              <p className="writing-warning" role="alert">
                {ERROR_MESSAGES[chapter.error_code] ||
                  "本次写作未完成，已保存的旧稿仍然可读。"}
              </p>
            )}
            {active(chapter) && (
              <p role="status" className="writing-warning">
                {statusText[chapter.status]}
                ，完成后会自动显示，刷新不会丢失任务。
              </p>
            )}
            <ChapterBody
              key={chapter.id}
              book={data}
              chapter={chapter}
              busy={busy}
              onEditing={setEditing}
            />
          </article>
        )}
      </section>
    </div>
  );
}

function ChapterBody({
  book,
  chapter,
  busy,
  onEditing,
}: {
  book: Book;
  chapter: BookChapter;
  busy: boolean;
  onEditing: (value: boolean) => void;
}) {
  const cache = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(chapter.current?.title || chapter.title);
  const [body, setBody] = useState(chapter.current?.body || "");
  const [editVersion, setEditVersion] = useState(chapter.version_number);
  const [showHistory, setShowHistory] = useState(false);
  const [version, setVersion] = useState(0);
  const history = useQuery({
    queryKey: ["book-versions", book.id, chapter.chapter_id],
    queryFn: () => booksApi.history(book.id, chapter.chapter_id),
    enabled: showHistory,
  });
  const save = useMutation({
    mutationFn: () =>
      booksApi.edit(book.id, chapter.chapter_id, {
        expected_version: editVersion,
        title,
        body,
      }),
    onSuccess: (updated) => {
      setEditing(false);
      onEditing(false);
      cache.setQueryData(["book", book.id], updated);
      void cache.invalidateQueries({ queryKey: ["books"] });
      void cache.invalidateQueries({
        queryKey: ["book-versions", book.id, chapter.chapter_id],
      });
    },
  });
  if (!chapter.current)
    return (
      <div className="writing-empty">
        <BookOpenText size={32} />
        <p>本章尚未成稿。</p>
        <p>
          有资料后点击“生成本章”。素材不足时，请继续采访，记录具体的人物、事件和细节。
        </p>
        <Link to="/interviews">前往采访 →</Link>
      </div>
    );
  const visible =
    history.data?.find((r) => r.version_number === version) || chapter.current;
  return (
    <div className="manuscript-pages">
      <div className="writing-buttons">
        {!editing && (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => {
              setTitle(chapter.current!.title);
              setBody(chapter.current!.body);
              setEditVersion(chapter.version_number);
              setEditing(true);
              onEditing(true);
              setVersion(0);
            }}
          >
            编辑正文
          </Button>
        )}
        <Button
          variant="ghost"
          disabled={editing}
          onClick={() => setShowHistory(!showHistory)}
        >
          版本记录
        </Button>
        <span>
          版本 {visible.version_number} · {visible.word_count} 字 ·{" "}
          {visible.author === "user" ? "人工编辑" : "AI 成稿，待核对"}
        </span>
      </div>
      {showHistory && (
        <div className="writing-history">
          <QueryState queries={[history]} loadingText="正在读取版本……" />
          {history.data?.map((r) => (
            <button
              key={r.id}
              disabled={editing}
              onClick={() => setVersion(r.version_number)}
              aria-pressed={r.id === visible.id}
            >
              版本 {r.version_number} ·{" "}
              {new Date(r.created_at).toLocaleString()} · {r.word_count}字
            </button>
          ))}
        </div>
      )}
      {editing ? (
        <form
          className="writing-editor"
          onSubmit={(e) => {
            e.preventDefault();
            if (!save.isPending) save.mutate();
          }}
        >
          <label>
            本章标题
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={180}
              required
            />
          </label>
          <label>
            正文
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              maxLength={12000}
              required
              rows={24}
            />
          </label>
          <p>保存为新版本，历史稿件继续保留。退出编辑前请先保存。</p>
          <div className="writing-buttons">
            <Button disabled={save.isPending || !body.trim() || !title.trim()}>
              保存新版本
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={save.isPending}
              onClick={() => {
                setEditing(false);
                onEditing(false);
                setBody(chapter.current!.body);
                setTitle(chapter.current!.title);
              }}
            >
              取消
            </Button>
          </div>
          <ErrorNotice error={save.error} />
        </form>
      ) : (
        <section className="writing-prose">
          <h3>{visible.title}</h3>
          {visible.body.split(/\n\s*\n/).map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </section>
      )}
    </div>
  );
}
