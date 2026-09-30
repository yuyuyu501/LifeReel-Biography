import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { BookWritingPage, BooksPage } from "./BooksPage";
import type { Book } from "../api/books";

const seed: Book = {
  id: "book-1",
  subject_id: "person-1",
  title: "合成人生书",
  target_words: 1000,
  chapters: [
    {
      id: "row-1",
      chapter_id: "chapter-1",
      title: "童年",
      order_index: 1,
      version_number: 1,
      status: "completed",
      source_count: 2,
      stale: false,
      job_id: null,
      error_code: null,
      current: {
        id: "version-1",
        version_number: 1,
        title: "童年记事",
        body: "第一段真实回忆。\n\n第二段真实回忆。",
        word_count: 1000,
        source_claim_ids: ["claim-1"],
        author: "ai",
        generation_model: "synthetic",
        created_at: "2026-09-30T00:00:00Z",
      },
    },
    {
      id: "row-2",
      chapter_id: "chapter-2",
      title: "求学",
      order_index: 2,
      version_number: 0,
      status: "empty",
      source_count: 0,
      stale: false,
      job_id: null,
      error_code: null,
      current: null,
    },
  ],
};
let book: Book;
const reply = (data: unknown, status = 200) =>
  ({ ok: status < 400, status, json: async () => data }) as Response;
function setup(path = "/books/book-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/books" element={<BooksPage />} />
          <Route path="/books/:bookId" element={<BookWritingPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}
beforeEach(() => {
  book = structuredClone(seed);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/v1/books" && init?.method === "POST")
        return reply(book, 201);
      if (url === "/v1/books") return reply([book]);
      if (url === "/v1/books/book-1") return reply(book);
      if (url === "/v1/persons")
        return reply([
          { id: "person-1", display_name: "合成人物", preferred_name: null },
        ]);
      if (url === "/v1/wallet")
        return reply({ prices: { script_billing_mode: "tokens" } });
      if (url.endsWith("/versions")) return reply([book.chapters[0].current]);
      if (url.endsWith("/generate"))
        return reply({ job_ids: ["job-1"], skipped_chapter_ids: [] }, 202);
      if (init?.method === "PATCH") {
        const data = JSON.parse(init.body as string);
        book.chapters[0].version_number = 2;
        book.chapters[0].current = {
          ...book.chapters[0].current!,
          ...data,
          version_number: 2,
          id: "version-2",
          author: "user",
        };
        return reply(book);
      }
      throw new Error("Unexpected URL: " + url);
    }),
  );
});

it("shows saved prose, target length and both export formats", async () => {
  setup();
  expect(await screen.findByText("第一段真实回忆。")).toBeInTheDocument();
  expect(screen.getByText("第二段真实回忆。")).toBeInTheDocument();
  expect(screen.getByText(/每章约1000字/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "导出 TXT" })).toHaveAttribute(
    "href",
    "/v1/books/book-1/export?format=txt",
  );
  expect(
    screen.getByRole("link", { name: "导出 Markdown" }),
  ).toBeInTheDocument();
});

it("creates or opens a selected person's book", async () => {
  setup("/books");
  fireEvent.change(await screen.findByLabelText("选择人物"), {
    target: { value: "person-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: /创建或打开书籍/ }));
  expect(await screen.findByText("第一段真实回忆。")).toBeInTheDocument();
});

it("queues a chapter with an idempotency key and expected revision", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "重新生成本章" }));
  await screen.findByText(/已安排 1 章写作/);
  const call = vi
    .mocked(fetch)
    .mock.calls.find(([path]) => String(path).endsWith("/generate"))!;
  const payload = JSON.parse(call[1]!.body as string);
  expect(payload.chapter_ids).toEqual(["chapter-1"]);
  expect(payload.expected_versions["chapter-1"]).toBe(1);
  expect(payload.idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
});

it("shows stale facts and preserves old prose on failed regeneration", async () => {
  book.chapters[0].stale = true;
  book.chapters[0].status = "failed";
  book.chapters[0].error_code = "BOOK_SOURCE_CHANGED";
  setup();
  expect(await screen.findByText(/采访资料已更正或补充/)).toBeInTheDocument();
  expect(screen.getByText("第一段真实回忆。")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "生成期间采访资料发生变化",
  );
});

it("restores queued state after opening and prevents duplicate generation", async () => {
  book.chapters[0].status = "queued";
  setup();
  expect(
    await screen.findByRole("button", { name: "正在写作……" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: /生成全书待写章节/ }),
  ).toBeDisabled();
  expect(screen.getByText(/刷新不会丢失任务/)).toBeInTheDocument();
});

it("edits manuscript and preserves version history", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "编辑正文" }));
  fireEvent.change(screen.getByLabelText("正文"), {
    target: { value: "用户更新的真实正文。" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));
  await waitFor(() =>
    expect(screen.queryByLabelText("正文")).not.toBeInTheDocument(),
  );
  expect(screen.getByText("用户更新的真实正文。")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "版本记录" }));
  expect(
    await screen.findByRole("button", { name: /版本 2/ }),
  ).toBeInTheDocument();
});

it("empty chapters point to interviews and cannot generate without sources", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: /求学/ }));
  expect(screen.getByRole("button", { name: "生成本章" })).toBeDisabled();
  expect(screen.getByRole("link", { name: /前往采访/ })).toHaveAttribute(
    "href",
    "/interviews",
  );
});

it("preserves unsaved text and its original revision when the server refreshes", async () => {
  const cache = setup();
  fireEvent.click(await screen.findByRole("button", { name: "编辑正文" }));
  fireEvent.change(screen.getByLabelText("正文"), {
    target: { value: "本地尚未保存的文字。" },
  });
  const updated = structuredClone(book);
  updated.chapters[0].version_number = 2;
  updated.chapters[0].current!.version_number = 2;
  updated.chapters[0].current!.body = "另一页面更新了正文。";
  act(() => cache.setQueryData(["book", "book-1"], updated));
  expect(screen.getByLabelText("正文")).toHaveValue("本地尚未保存的文字。");
  fireEvent.click(screen.getByRole("button", { name: "保存新版本" }));
  await waitFor(() => {
    const call = vi
      .mocked(fetch)
      .mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(call![1]!.body as string).expected_version).toBe(1);
  });
});
