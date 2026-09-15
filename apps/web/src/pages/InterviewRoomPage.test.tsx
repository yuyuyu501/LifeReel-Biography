import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { InterviewRoomPage } from "./InterviewRoomPage";

const recorder = vi.hoisted(() => ({
  isRecording: false,
  audioBlob: null,
  audioUrl: null,
  error: null,
  start: vi.fn(),
  stop: vi.fn(),
  clear: vi.fn(),
}));
vi.mock("../hooks/useAudioRecorder", () => ({ useAudioRecorder: () => recorder }));

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
let interviewRounds = rounds;
let workflowStatus = "completed";
let retryAllowed = true;
let retryAfter = 0;

beforeEach(() => {
  recorder.isRecording = false;
  interviewStatus = "completed";
  interviewRounds = rounds;
  workflowStatus = "completed";
  retryAllowed = true;
  retryAfter = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/v1/interviews/session-1/workspace")) {
      return response({
        session: {
          id: "session-1",
          subject_id: "person-1",
          chapter_id: "chapter-1",
          status: interviewStatus,
          rounds: interviewRounds,
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
          status: workflowStatus,
          retry_allowed: retryAllowed,
          retry_after_seconds: retryAfter,
          error_code: workflowStatus === "failed" ? "SCRIPT_LLM_RESPONSE_INVALID" : null,
          job_id: "job-1",
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
  for (const name of ["剧情", "分镜", "人物对话", "场景描述"]) {
    expect(screen.getByRole("heading", { name })).toBeInTheDocument();
  }
  expect(screen.getByText("已同步")).toBeInTheDocument();
  expect(screen.queryByText("第 2 稿")).not.toBeInTheDocument();
  expect(screen.queryByText("01")).not.toBeInTheDocument();
  expect(screen.queryByText("接下来还需补充")).not.toBeInTheDocument();
  expect(screen.queryByText("后来影响")).not.toBeInTheDocument();
});

test.each(["active", "paused", "completed"])("keeps the composer visible for legacy %s conversations", async (status) => {
  interviewStatus = status;
  renderPage();
  expect(await screen.findByRole("textbox", { name: /^说说这段往事/ })).toBeInTheDocument();
  expect(screen.getByText("添加素材")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "录制原声" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /温暖结束|暂停采访|继续采访/ })).not.toBeInTheDocument();
  expect(screen.queryByText(/^(进行中|已暂停|已完成)$/)).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([url]) => /\/(pause|resume|complete)$/.test(String(url)))).toBe(false);
});

test("appends a message when the last historical round has already been answered", async () => {
  interviewRounds = rounds.slice(0, 2);
  renderPage();
  fireEvent.change(await screen.findByRole("textbox", { name: /^说说这段往事/ }), {
    target: { value: "我还记得母亲带我去赶海。" },
  });
  fireEvent.click(screen.getByRole("button", { name: /发送并更新剧本/ }));
  await waitFor(() => {
    const call = vi.mocked(fetch).mock.calls.find(([url, init]) => String(url).endsWith("/turns") && init?.method === "POST");
    expect(call).toBeDefined();
    const body = JSON.parse(call![1]!.body as string);
    expect(body.answer_text).toBe("我还记得母亲带我去赶海。");
    expect(body.round_id).toBeUndefined();
  });
});

test("keeps the composer visible while the previous turn is processing", async () => {
  interviewRounds = rounds.slice(0, 2);
  workflowStatus = "running";
  const view = renderPage();
  const composer = await screen.findByRole("textbox", { name: /^说说这段往事/ });
  fireEvent.change(composer, { target: { value: "下一段回忆" } });
  expect(composer).toBeEnabled();
  expect(screen.getByRole("button", { name: /正在整理/ })).toBeDisabled();
  view.unmount();
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

test("uses labeled tools and a visible send label without a pricing banner", async () => {
  renderPage();
  await screen.findByRole("textbox", { name: "说说这段往事" });
  const send = screen.getByRole("button", { name: "发送并更新剧本" });
  expect(send).toBeDisabled();
  expect(send).toHaveTextContent("发送");
  expect(screen.queryByText(/官方标准价|查看钱包|不再按章收费/)).not.toBeInTheDocument();
  expect(send).toHaveAttribute("title", "发送并更新剧本");
  expect(screen.getByLabelText("添加素材")).toHaveAttribute("type", "file");
  fireEvent.click(screen.getByRole("button", { name: "录制原声" }));
  expect(recorder.start).toHaveBeenCalled();
});

test("allows a new message after a failed script update", async () => {
  workflowStatus = "failed";
  renderPage();
  fireEvent.change(await screen.findByRole("textbox", { name: "说说这段往事" }), {
    target: { value: "现在我已经退休，和老伴住在杭州。" },
  });
  const send = screen.getByRole("button", { name: "发送并更新剧本" });
  expect(send).toBeEnabled();
  expect(screen.getByRole("button", { name: "重新整理" })).toBeEnabled();
  expect(screen.getByText("最新内容尚未同步")).toBeInTheDocument();
  expect(screen.queryByText("已同步")).not.toBeInTheDocument();
  expect(screen.getByText("我从海边长大。")).toBeInTheDocument();
  fireEvent.click(send);
  await waitFor(() => {
    const call = vi.mocked(fetch).mock.calls.find(([url, init]) => String(url).endsWith("/turns") && init?.method === "POST");
    expect(call).toBeDefined();
    expect(JSON.parse(call![1]!.body as string).answer_text).toBe("现在我已经退休，和老伴住在杭州。");
  });
});

test("disables exhausted retries while retaining the conversation", async () => {
  workflowStatus = "failed";
  retryAllowed = false;
  renderPage();
  expect(await screen.findByRole("button", { name: "已达重试上限" })).toBeDisabled();
  expect(screen.getByText("我的家乡靠海。")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "说说这段往事" })).toBeEnabled();
});

test("shows retry cooldown from the server", async () => {
  workflowStatus = "failed";
  retryAfter = 20;
  const view = renderPage();
  expect(await screen.findByRole("button", { name: "稍后可重试" })).toBeDisabled();
  view.unmount();
});

test("waits for recording to stop before allowing a turn to be sent", async () => {
  recorder.isRecording = true;
  renderPage();
  fireEvent.change(await screen.findByRole("textbox", { name: "说说这段往事" }), {
    target: { value: "正在录音时写下的回忆" },
  });
  expect(screen.getByRole("button", { name: "发送并更新剧本" })).toBeDisabled();
  const stop = screen.getByRole("button", { name: "停止录音" });
  expect(stop).toHaveAttribute("aria-pressed", "true");
  fireEvent.submit(stop.closest("form")!);
  expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith("/turns"))).toBe(false);
  fireEvent.click(stop);
  expect(recorder.stop).toHaveBeenCalled();
});
