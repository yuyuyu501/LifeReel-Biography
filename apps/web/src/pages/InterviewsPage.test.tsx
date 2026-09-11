import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { InterviewsPage } from "./InterviewsPage";

const person = {
  id: "person-1",
  display_name: "林秀兰",
  preferred_name: "林奶奶",
  is_subject: true,
};
const chapterOne = { id: "chapter-1", order_index: 1, title: "我是谁", description: "从姓名与家乡说起。" };
const chapterTwo = { id: "chapter-2", order_index: 2, title: "童年岁月", description: "记下小时候的生活。" };
const currentSession = {
  id: "session-current",
  subject_id: person.id,
  chapter_id: chapterOne.id,
  status: "paused",
  round_count: 2,
  started_at: "2026-09-07T00:00:00Z",
  rounds: [{ id: "round-1", answer_text: "我出生在泉州。" }, { id: "round-2", answer_text: null }],
};
const oldSession = { ...currentSession, id: "session-old", status: "completed", started_at: "2026-09-06T00:00:00Z" };

function response(payload: unknown, status = 200) {
  return { ok: true, status, json: async () => payload } as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/v1/persons")) return response([person]);
    if (url.endsWith("/v1/chapters")) return response([chapterOne, chapterTwo]);
    if (url.endsWith("/v1/interviews") && init?.method === "POST") {
      return response({ ...currentSession, id: "session-new", chapter_id: chapterTwo.id, status: "active", rounds: [] }, 201);
    }
    if (url.endsWith("/v1/interviews")) return response([currentSession, oldSession]);
    return response([]);
  }) as unknown as typeof fetch);
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/interviews"]}>
        <Routes>
          <Route path="/interviews" element={<InterviewsPage />} />
          <Route path="/interviews/:id" element={<div>采访对话页</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("opens the saved chapter conversation instead of creating another one", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "章节采访" })).toBeInTheDocument();
  expect((await screen.findAllByText(/已保存 1 轮回答/)).length).toBeGreaterThan(0);
  expect(screen.queryByText(/^(进行中|已暂停|已完成|未开始)$/)).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: /继续这一章/ }));
  expect(await screen.findByText("采访对话页")).toBeInTheDocument();
  expect(vi.mocked(fetch)).not.toHaveBeenCalledWith(
    "/v1/interviews",
    expect.objectContaining({ method: "POST" }),
  );
});

test("creates a conversation only for a chapter that has not started", async () => {
  renderPage();
  await screen.findByRole("heading", { name: "章节采访" });
  fireEvent.click(await screen.findByRole("button", { name: /开始这一章/ }));
  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
    "/v1/interviews",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ subject_id: person.id, chapter_id: chapterTwo.id }),
    }),
  ));
  expect(await screen.findByText("采访对话页")).toBeInTheDocument();
});

test("keeps legacy duplicate sessions available as past interviews", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "过往采访" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /我是谁.*已保存 1 轮回答/ })).toHaveAttribute(
    "href",
    "/interviews/session-old",
  );
});
