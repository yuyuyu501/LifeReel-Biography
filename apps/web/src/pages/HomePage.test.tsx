import type { InterviewSession } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import { booksApi, type Book } from "../api/books";
import { HomePage } from "./HomePage";

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listPersons").mockResolvedValue([]);
  vi.spyOn(api, "listInterviews").mockResolvedValue([]);
  vi.spyOn(api, "listEvidence").mockResolvedValue([]);
  vi.spyOn(api, "listScripts").mockResolvedValue([]);
  vi.spyOn(booksApi, "list").mockResolvedValue([]);
});
function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
test("empty sessions and book shells do not imply recorded interviews or completed books", async () => {
  vi.mocked(api.listInterviews).mockResolvedValue([
    {
      id: "empty",
      profile_id: "profile",
      status: "active",
      rounds: [{ answer_text: null }],
    } as InterviewSession,
  ]);
  vi.mocked(booksApi.list).mockResolvedValue([
    { id: "book", chapters: [{ current: null }] } as Book,
  ]);
  show();
  expect(
    await screen.findByText("0 本已有成稿 · 1 本书籍"),
  ).toBeInTheDocument();
  expect(screen.getByText("书稿改编 · 账号私密")).toBeInTheDocument();
  expect(screen.queryByText("发布需授权")).not.toBeInTheDocument();
  expect(screen.queryByText("工作动态")).not.toBeInTheDocument();
  expect(screen.queryByText("继续上次采访")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /采访 尚未开始/ })).not.toHaveClass(
    "done",
  );
  expect(screen.getByRole("link", { name: /写书/ })).not.toHaveClass("done");
});
test("counts saved answers and does not suggest resuming a completed interview", async () => {
  vi.mocked(api.listInterviews).mockResolvedValue([
    {
      id: "active",
      profile_id: "profile",
      status: "active",
      updated_at: "2026-11-01",
      round_count: 3,
      rounds: [{ answer_text: "1970年出生" }, { answer_text: null }],
    } as InterviewSession,
    {
      id: "completed",
      profile_id: "profile",
      status: "completed",
      updated_at: "2026-11-02",
      rounds: [{ answer_text: "已讲完" }],
    } as InterviewSession,
  ]);
  show();
  expect(
    await screen.findByText("已记录 1 轮回答，原有内容均已保存。"),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /进入处理/ })).toHaveAttribute(
    "href",
    "/interviews/active",
  );
  expect(screen.getByText("2 份对话记录")).toBeInTheDocument();
});
