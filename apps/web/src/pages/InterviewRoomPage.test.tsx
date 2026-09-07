import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { InterviewRoomPage } from "./InterviewRoomPage";

const rounds = [
  {
    id: "round-old-empty",
    round_index: 1,
    question_text: "旧会话里没有回答的问题",
    answer_text: null,
    source_asset_id: null,
  },
  {
    id: "round-answered",
    round_index: 2,
    question_text: "请说说您的家乡。",
    answer_text: "我的家乡靠海。",
    source_asset_id: null,
  },
  {
    id: "round-current",
    round_index: 3,
    question_text: "海边给您留下了什么印象？",
    answer_text: null,
    source_asset_id: null,
  },
];

function response(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response;
}

let interviewStatus = "completed";

beforeEach(() => {
  interviewStatus = "completed";
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/resume") && init?.method === "POST") {
      interviewStatus = "active";
    }
    if (url.endsWith("/v1/interviews/session-1/workspace")) {
      return response({
        session: {
          id: "session-1",
          subject_id: "person-1",
          chapter_id: "chapter-1",
          status: interviewStatus,
          rounds,
        },
        assets: [],
        script: {
          id: "script-1",
          subject_id: "person-1",
          version_number: 2,
          scenes: [{
            id: "scene-1",
            chapter_id: "chapter-1",
            heading: "海边的家乡",
            narration: "我从海边长大。",
            visual_prompt: "清晨的海边村庄。",
            duration_seconds: 12,
            source_claim_ids: ["claim-1"],
          }],
        },
        latest_workflow: {
          id: "workflow-completed",
          status: "completed",
          error_code: null,
          missing_topics: ["后来影响"],
        },
      });
    }
    if (url.endsWith("/v1/evidence/assets") && init?.method === "POST") {
      return response({ id: "asset-1", original_filename: "旧照片.jpg" });
    }
    if (url.endsWith("/v1/interviews/session-1/turns") && init?.method === "POST") {
      return response({ id: "workflow-1", status: "completed" });
    }
    if (url.includes("/v1/interviews/session-1")) return response({ status: interviewStatus });
    if (url.endsWith("/v1/chapters")) return response([{ id: "chapter-1", title: "故乡" }]);
    return response([]);
  }) as unknown as typeof fetch);
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/interviews/session-1"]}>
        <Routes>
          <Route path="/interviews/:id" element={<InterviewRoomPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("shows saved answers and only the current unanswered question", async () => {
  renderPage();
  expect(await screen.findByText("我的家乡靠海。")).toBeInTheDocument();
  expect(screen.getByText("请说说您的家乡。")).toBeInTheDocument();
  expect(screen.getByText("海边给您留下了什么印象？")).toBeInTheDocument();
  expect(screen.queryByText("旧会话里没有回答的问题")).not.toBeInTheDocument();
  expect(screen.getByText("海边的家乡")).toBeInTheDocument();
  expect(screen.getByText("已同步")).toBeInTheDocument();
  expect(screen.queryByText("第 2 稿")).not.toBeInTheDocument();
  expect(screen.queryByText("01")).not.toBeInTheDocument();
  expect(screen.queryByText("接下来还需补充")).not.toBeInTheDocument();
  expect(screen.queryByText("后来影响")).not.toBeInTheDocument();
});

test("resumes a completed conversation in place", async () => {
  renderPage();
  fireEvent.click(await screen.findByRole("button", { name: "继续采访" }));
  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
    "/v1/interviews/session-1/resume",
    expect.objectContaining({ method: "POST" }),
  ));
  expect(await screen.findByRole("textbox", { name: /^说说这段往事/ })).toBeInTheDocument();
  expect(screen.getByText("添加素材")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "温暖结束" })).toBeInTheDocument();
});

test("adds a material in the composer and submits it through the turn workflow", async () => {
  interviewStatus = "active";
  const view = renderPage();
  await screen.findByRole("textbox", { name: /^说说这段往事/ });
  const input = view.container.querySelector<HTMLInputElement>('input[type="file"]');
  expect(input).not.toBeNull();
  const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], "旧照片.jpg", {
    type: "image/jpeg",
  });

  fireEvent.change(input!, { target: { files: [file] } });
  expect(await screen.findByText("旧照片.jpg")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /发送并更新剧本/ }));

  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
    "/v1/evidence/assets",
    expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
  ));
  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
    "/v1/interviews/session-1/turns",
    expect.objectContaining({ method: "POST" }),
  ));
});
