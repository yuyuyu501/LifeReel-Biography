import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { ScriptBookPage } from "./ScriptBookPage";
import { ScriptLibraryPage } from "./ScriptLibraryPage";
import { StudioPage } from "./StudioPage";

const person = {
  id: "person-1",
  tenant_id: "tenant-1",
  display_name: "林秀兰",
  preferred_name: "林奶奶",
  birth_year: 1952,
  birthplace: "福建泉州",
  relation_to_owner: "外婆",
  is_subject: true,
  biography_note: null,
  is_minor: false,
  guardian_name: null,
  created_at: "2026-09-04T00:00:00Z",
  updated_at: "2026-09-04T00:00:00Z",
};

const project = {
  id: "script-1",
  subject_id: person.id,
  title: "海风吹过的童年",
  mode: "multi_chapter",
  status: "draft",
  audience: "family",
  source_claim_ids: ["claim-1"],
  version_number: 1,
  generation_provider: "openai-compatible",
  generation_model: "gpt-test",
  created_at: "2026-09-04T00:00:00Z",
  updated_at: "2026-09-04T00:00:00Z",
  scenes: [{
    id: "scene-1",
    chapter_id: "chapter-1",
    order_index: 1,
    heading: "泉州旧巷",
    narration: "我小时候住在泉州，清晨总能听见巷口的叫卖声。",
    visual_prompt: "泉州旧巷",
    duration_seconds: 12,
    source_claim_ids: ["claim-1"],
  }, {
    id: "scene-2",
    chapter_id: null,
    order_index: 2,
    heading: "远行求学",
    narration: "十八岁那年，我第一次离开家乡去读书。",
    visual_prompt: "旧火车站的远景",
    duration_seconds: 15,
    source_claim_ids: ["claim-2"],
  }],
  shots: [],
};

const chapter = {
  id: "chapter-1",
  order_index: 1,
  title: "童年岁月",
  description: null,
  opening_questions: [],
  is_system: true,
};

function response(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response;
}

function renderPage(element: React.ReactNode, initialEntry: string, routePath = "*") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes><Route path={routePath} element={element} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/v1/persons")) return response([person]);
    if (url.endsWith("/v1/scripts")) return response([project]);
    if (url.endsWith("/v1/chapters")) return response([chapter]);
    return response([]);
  }) as unknown as typeof fetch);
});

test("groups every person's scripts into one book", async () => {
  renderPage(<ScriptLibraryPage />, "/scripts");
  expect(await screen.findByRole("heading", { name: "一位家人，一本人生之书" })).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: /林奶奶/ })).toHaveAttribute("href", "/scripts/person-1");
  expect(screen.getByText("已有剧本")).toBeInTheDocument();
  expect(screen.getByText("2 个章节")).toBeInTheDocument();
});

test("opens a family book with generation and chapter reading", async () => {
  renderPage(<ScriptBookPage />, "/scripts/person-1", "/scripts/:subjectId");
  expect(await screen.findByRole("heading", { name: "林奶奶的人生剧本" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生成整本剧本" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "章节目录" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "剧本版本" })).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "泉州旧巷" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "远行求学" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /02.*远行求学/ }));
  expect(screen.getByRole("heading", { name: "远行求学" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "泉州旧巷" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生成影像" })).not.toBeInTheDocument();
});

test("keeps the script book focused on reading and generation", async () => {
  renderPage(<ScriptBookPage />, "/scripts/person-1", "/scripts/:subjectId");
  await screen.findByRole("heading", { name: "章节目录" });

  expect(screen.getByLabelText("章节目录")).toBeInTheDocument();
  expect(screen.queryByRole("checkbox", { name: "选择第 1 章" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "通过" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "驳回" })).not.toBeInTheDocument();
  expect(screen.queryByText("待人工审核")).not.toBeInTheDocument();
});

test("keeps the image studio focused on production", async () => {
  renderPage(<StudioPage />, "/studio");
  expect(await screen.findByRole("heading", { name: "影像制作" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "生成影像" })).toBeDisabled();
  expect(screen.queryByText("待人工审核")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生成剧本" })).not.toBeInTheDocument();
});
