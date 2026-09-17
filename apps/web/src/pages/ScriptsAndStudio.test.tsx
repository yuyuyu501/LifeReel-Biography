import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes><Route path={routePath} element={element} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, queryClient };
}

beforeEach(() => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/v1/wallet")) return response({ paid_cents: 0, bonus_cents: 2000, frozen_cents: 0, available_cents: 2000, prices: { video_cents_per_second: 80, script_chapter_cents: 40 } });
    if (url.endsWith("/v1/persons")) return response([person]);
    if (url.endsWith("/v1/scripts")) return response([project]);
    if (url.endsWith("/v1/chapters")) return response([chapter]);
    if (url.endsWith("/v1/production/settings")) return response({
      provider: "volcengine-seedance", model: "doubao-seedance-1-0-pro-fast-251015",
      resolution: "720p", ratio: "16:9", duration_seconds: 5, generate_audio: false,
    });
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
  expect(screen.getByRole("button", { name: "生成所选章节" })).toBeInTheDocument();
  expect(screen.queryByText("生成结构")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "多章节" })).not.toBeInTheDocument();
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

test("generating chapter two selects its new scene and never submits a multi-chapter request", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const updated = { ...project, scenes: [project.scenes[0], {
    ...project.scenes[1], id: "new-scene-2", chapter_id: "chapter-2", heading: "更新后的求学往事",
  }] };
  let generated = false;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/v1/chapters")) return response([chapter,
      { ...chapter, id: "chapter-2", order_index: 2, title: "求学" }]);
    if (String(input).endsWith("/v1/scripts/generate")) {
      expect(JSON.parse(String(init?.body))).toMatchObject({ mode: "single_chapter", chapter_id: "chapter-2" });
      generated = true;
      return response(updated);
    }
    if (generated && String(input).endsWith("/v1/scripts")) return response([updated]);
    return original(input, init);
  });
  renderPage(<ScriptBookPage />, "/scripts/person-1", "/scripts/:subjectId");
  fireEvent.click(await screen.findByRole("button", { name: /02.*求学.*尚未生成/ }));
  expect(screen.queryByRole("combobox", { name: "采访章节" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "生成所选章节" }));
  expect(await screen.findByRole("heading", { name: "更新后的求学往事" })).toBeVisible();
  await waitFor(() => expect(screen.getByRole("button", { name: "生成所选章节" })).toBeEnabled());
  expect(screen.queryByRole("heading", { name: "泉州旧巷" })).not.toBeInTheDocument();
});

test("keeps the image studio focused on production", async () => {
  renderPage(<StudioPage />, "/studio");
  expect(await screen.findByRole("heading", { name: "影像制作" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "生成影像" })).toBeEnabled();
  expect(screen.queryByText("制作授权待补齐")).not.toBeInTheDocument();
  expect(screen.queryByText("任务记录")).not.toBeInTheDocument();
  expect(screen.queryByText("生成模型")).not.toBeInTheDocument();
  expect(screen.queryByText("doubao-seedance-1-0-pro-fast-251015")).not.toBeInTheDocument();
  expect(screen.getByLabelText("视频参数").querySelectorAll("dt")).toHaveLength(4);
  expect(screen.getByText("720p")).toBeInTheDocument();
  expect(screen.getByText("16:9")).toBeInTheDocument();
  expect(screen.getByText("5 秒")).toBeInTheDocument();
  expect(screen.getByText("无声片段")).toBeInTheDocument();
  expect(screen.queryByText("待人工审核")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生成剧本" })).not.toBeInTheDocument();
});

test("switches chapters and submits only the selected chapter", async () => {
  renderPage(<StudioPage />, "/studio");
  await screen.findByRole("button", { name: "生成影像" });
  fireEvent.click(screen.getByRole("tab", { name: "本章剧本" }));
  expect(screen.getByText(project.scenes[0].narration)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /02.*远行求学/ }));
  expect(screen.getByText(project.scenes[1].narration)).toBeVisible();
  expect(screen.queryByText(project.scenes[0].narration)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "视频预览" }));
  expect(screen.getByText(project.scenes[1].narration)).not.toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "生成影像" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/v1/production/runs"),
    expect.objectContaining({ method: "POST", body: JSON.stringify({
      project_id: project.id, scene_id: "scene-2", audience: "family", quoted_amount_cents: 400,
    }) }),
  ));
});

test("starts immediately without a confirmation dialog or quote notice", async () => {
  vi.mocked(window.confirm).mockReturnValue(false);
  renderPage(<StudioPage />, "/studio");
  fireEvent.click(await screen.findByRole("button", { name: "生成影像" }));
  expect(window.confirm).not.toHaveBeenCalled();
  expect(screen.queryByText(/本次报价/)).not.toBeInTheDocument();
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
});

test.each([0, -400])("disables new generation when available balance is %s", async (balance) => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/v1/wallet")
    ? response({ available_cents: balance, prices: { video_billing_mode: "tokens", video_reserve_cents: 2400 } })
    : original(input, init));
  renderPage(<StudioPage />, "/studio");
  const button = await screen.findByRole("button", { name: "生成影像" });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});

test("a positive balance below the full hold still permits one video", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/v1/wallet")
    ? response({ available_cents: 1, prices: { video_billing_mode: "tokens", video_reserve_cents: 2400 } })
    : original(input, init));
  renderPage(<StudioPage />, "/studio");
  const button = await screen.findByRole("button", { name: "生成影像" });
  expect(button).toBeEnabled();
  fireEvent.click(button);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/v1/production/runs"),
    expect.objectContaining({ method: "POST", body: JSON.stringify({ project_id: project.id,
      scene_id: "scene-1", audience: "family", quoted_amount_cents: 2400 }) })));
  expect(window.confirm).not.toHaveBeenCalled();
});

test("script retry reuses its update ID and the next success uses a new ID", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const requests: Array<{ idempotency_key: string; mode: string; chapter_id: string }> = [];
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/v1/scripts/generate")) {
      requests.push(JSON.parse(String(init?.body)));
      if (requests.length === 1) return { ok: false, status: 502, json: async () => ({ error: { code: "SCRIPT_LLM_REQUEST_FAILED" } }) } as Response;
      return response(project);
    }
    return original(input, init);
  });
  renderPage(<ScriptBookPage />, "/scripts/person-1", "/scripts/:subjectId");
  const button = await screen.findByRole("button", { name: "生成所选章节" });
  fireEvent.click(button);
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "生成所选章节" }));
  await waitFor(() => expect(requests).toHaveLength(2));
  await waitFor(() => expect(screen.getByRole("button", { name: "生成所选章节" })).toBeEnabled());
  expect(requests[0].mode).toBe("single_chapter");
  expect(requests[0].chapter_id).toBe("chapter-1");
  expect(requests[0].idempotency_key).toBeTruthy();
  expect(requests[1].idempotency_key).toBe(requests[0].idempotency_key);
  fireEvent.click(screen.getByRole("button", { name: "生成所选章节" }));
  await waitFor(() => expect(requests).toHaveLength(3));
  expect(requests[2].idempotency_key).not.toBe(requests[0].idempotency_key);
});

test("segmented production shows chapter duration and checkpoint progress", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/v1/production/settings")) return response({
      provider: "volcengine-seedance", model: "doubao-seedance-2-0-mini-260615",
      resolution: "720p", ratio: "16:9", duration_seconds: 5, generate_audio: true,
      mode: "segmented", max_segment_seconds: 15,
    });
    if (String(input).endsWith("/v1/production/runs")) return response([{
      id: "run-segmented", project_id: project.id, status: "running",
      provider: "volcengine-seedance", audience: "family", assets: [],
      created_at: "2026-09-08T00:00:00Z",
      output_manifest: { scene_id: "scene-1", stage: "generating", completed_segments: 1,
        segments: [{ status: "completed" }, { status: "submitted" }] },
    }]);
    return original(input, init);
  });
  renderPage(<StudioPage />, "/studio");
  expect(await screen.findByText("整章生成")).toBeVisible();
  expect(screen.queryByText("生成模型")).not.toBeInTheDocument();
  expect(screen.queryByText("doubao-seedance-2-0-mini-260615")).not.toBeInTheDocument();
  expect(screen.getByText("12 秒")).toBeVisible();
  expect(screen.queryByText("5 秒")).not.toBeInTheDocument();
  expect(screen.getByText("原生音频")).toBeVisible();
  expect(await screen.findByText("已完成 1 / 2 段")).toBeVisible();
  expect(screen.getByRole("button", { name: "正在生成" })).toBeDisabled();
});

test("changing family clears the previous chapter and video", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/v1/persons")) return response([person, { ...person, id: "person-2", preferred_name: "另一位家人" }]);
    return original(input, init);
  });
  renderPage(<StudioPage />, "/studio");
  await screen.findByRole("button", { name: "生成影像" });
  fireEvent.change(screen.getByLabelText("制作对象"), { target: { value: "person-2" } });
  expect(screen.getByText("还没有可制作的章节")).toBeVisible();
  expect(screen.queryByRole("button", { name: "生成影像" })).not.toBeInTheDocument();
  expect(screen.queryByText(project.scenes[0].narration)).not.toBeInTheDocument();
});

test.each([
  ["PLAN_DURATION_MISMATCH", "分镜时长与分配方案不一致，暂未生成视频"],
  ["PLAN_NARRATION_MISMATCH", "分镜旁白与原剧本不一致，暂未生成视频"],
  ["PLAN_SCHEMA_INVALID", "分镜字段缺失或格式不符合要求，暂未生成视频"],
  ["PLAN_BOUNDARY_INVALID", "旁白分段位置不正确，暂未生成视频"],
  [undefined, "分镜结果未通过校验，暂未生成视频"],
])("shows specific planning failure %s without raw AI output", async (code, message) => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/v1/production/runs")) return response([{
      id: "plan-failed", project_id: project.id, job_id: "job-1", status: "failed",
      error_message: "VIDEO_PLAN_INVALID", assets: [], created_at: "2026-09-14T00:00:00Z",
      output_manifest: { scene_id: "scene-1", planning_diagnostics: code ? [{
        attempt: 3, diagnostic_id: "private-diagnostic", issues: [{ code, field: "segments.0" }],
      }] : undefined },
    }]);
    return original(input, init);
  });
  renderPage(<StudioPage />, "/studio");
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.queryByText("private-diagnostic")).not.toBeInTheDocument();
  expect(screen.queryByText("分镜未完整保留剧本，请重试")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新生成" })).toBeEnabled();
});

test("compares a video with its saved script and isolates other chapters", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/v1/production/runs")) return response([{
      id: "run-1", project_id: project.id, status: "completed", provider: "volcengine-seedance",
      audience: "family", assets: [], created_at: "2026-09-08T00:00:00Z",
      output_manifest: {
        scene_id: "scene-1", script_version: 1,
        script_snapshot: [{ ...project.scenes[0], narration: "生成当时的旁白" }],
      },
    }]);
    return original(input, init);
  });
  renderPage(<StudioPage />, "/studio");
  await screen.findByRole("tab", { name: "本章剧本" });
  fireEvent.click(screen.getByRole("tab", { name: "本章剧本" }));
  expect(screen.getByText(project.scenes[0].narration)).toBeVisible();
  expect(screen.getByRole("button", { name: "编辑本章剧本" })).toBeEnabled();
  expect(screen.getByText("生成当时的旁白")).not.toBeVisible();
  fireEvent.click(screen.getByText("生成时剧本（只读）"));
  expect(screen.getByText("生成当时的旁白")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /02.*远行求学/ }));
  expect(screen.queryByText("生成当时的旁白")).not.toBeInTheDocument();
  expect(screen.getByText(project.scenes[1].narration)).toBeVisible();
});

const rejectedRun = {
  id: "blocked-run", project_id: project.id, job_id: "blocked-job", status: "failed",
  error_message: "VIDEO_REFERENCE_REJECTED", provider: "volcengine-seedance", assets: [],
  created_at: "2026-09-14T01:12:10Z", updated_at: "2026-09-14T01:15:43Z",
  recovery: { code: "VIDEO_REFERENCE_REJECTED", segment_index: 1, rejected_asset_ids: ["rejected-image"] },
  output_manifest: { scene_id: "scene-1", script_version: 1,
    segments: [{ status: "completed", duration_seconds: 15 }, { status: "pending", duration_seconds: 15 }],
    billing: { status: "settled", charged_cents: 1121 } },
};

test("shows only the newest chapter run, regardless of response order", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const older = { ...rejectedRun, id: "old", created_at: "2026-09-14T00:00:00Z" };
  const latest = { ...rejectedRun, id: "new", created_at: "2026-09-15T00:00:00Z",
    status: "completed", error_message: null, recovery: null,
    assets: [{ id: "latest-video", mime_type: "video/mp4" }] };
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/v1/production/runs")
    ? response([older, latest]) : original(input, init));
  renderPage(<StudioPage />, "/studio");
  const video = await screen.findByLabelText("泉州旧巷视频");
  expect(video).toHaveAttribute("src", expect.stringContaining("latest-video"));
  expect(screen.queryByText("生成版本")).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /01.*泉州旧巷/ })).toHaveTextContent("已完成");
});

test("does not show an old successful video as a failed new generation", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/v1/production/runs")
    ? response([{ ...rejectedRun, created_at: "2026-09-13T00:00:00Z", status: "completed",
      assets: [{ id: "old-video", mime_type: "video/mp4" }], error_message: null, recovery: null },
    { ...rejectedRun, output_manifest: { scene_id: "scene-1" } }]) : original(input, init));
  renderPage(<StudioPage />, "/studio");
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("泉州旧巷视频")).not.toBeInTheDocument();
  expect(screen.queryByText("生成版本")).not.toBeInTheDocument();
});
const replacementImage = { id: "replacement-image", subject_id: person.id, kind: "photo", status: "ready",
  mime_type: "image/png", byte_size: 1000, original_filename: "老宅.png" };

function mockRecovery(files: unknown[] = [replacementImage]) {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith("/v1/production/runs")) return response([rejectedRun]);
    if (url.includes("/v1/evidence/assets?")) return response(files);
    if (url.endsWith("/reference")) return response({ ...rejectedRun, status: "queued", recovery: null });
    return original(input, init);
  });
}

test("rejected references use one generation action and keep selection in the script", async () => {
  mockRecovery([replacementImage, { ...replacementImage, id: "rejected-image", original_filename: "被拒.png" },
    { ...replacementImage, id: "foreign-image", subject_id: "person-2", original_filename: "别人的.png" }]);
  renderPage(<StudioPage />, "/studio");
  expect(await screen.findByRole("alert")).toHaveTextContent("本章素材未通过");
  expect(screen.queryByText("视频服务暂时无法连接")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重新尝试" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新生成" })).toBeEnabled();
  expect(screen.getByLabelText("第 1 段视频")).toHaveAttribute("src", expect.stringContaining("/blocked-run/segments/0/content"));
  expect(screen.queryByLabelText("参考图片")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "使用此图继续生成" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "本章剧本" }));
  expect(screen.getByRole("region", { name: "本章形象" })).toBeVisible();
  expect(window.confirm).not.toHaveBeenCalled();
});

test("retrying a rejected chapter uses its existing job and disables repeated clicks", async () => {
  mockRecovery([{ ...replacementImage, id: "rejected-image", original_filename: "被拒.png" }]);
  const original = vi.mocked(fetch).getMockImplementation()!;
  let resolveRetry: (value: Response) => void;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/blocked-job/retry")) {
      return new Promise<Response>((resolve) => { resolveRetry = resolve; });
    }
    return original(input, init);
  });
  renderPage(<StudioPage />, "/studio");
  fireEvent.click(await screen.findByRole("button", { name: "重新生成" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "正在生成" })).toBeDisabled());
  expect(screen.queryByRole("button", { name: "重新尝试" })).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/blocked-job/retry"), expect.objectContaining({ method: "POST" }));
  await act(async () => resolveRetry!(response({ id: "blocked-job", status: "queued" })));
});

test("a failed run without images has no upload or replacement detour", async () => {
  mockRecovery([]);
  renderPage(<StudioPage />, "/studio");
  await screen.findByRole("alert");
  expect(screen.queryByText("暂无可用的图片素材")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "前往采访添加素材" })).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
});

test.each([undefined, "color-redraw-v1"])("a new prompt starts a new run instead of retrying version %s", async (previousVersion) => {
  mockRecovery([]);
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/v1/production/settings")) return response({
      provider: "volcengine-seedance", model: "doubao-seedance-2-0-mini-260615",
      mode: "segmented", reference_style: "color_redraw", resolution: "720p",
      reference_prompt_version: "ai-label-v2",
      ratio: "16:9", duration_seconds: 15, generate_audio: true,
    });
    if (String(input).endsWith("/v1/production/runs") && init?.method === "POST")
      return response({ ...rejectedRun, id: "new-run", status: "queued", recovery: null });
    if (String(input).endsWith("/v1/production/runs") && previousVersion)
      return response([{ ...rejectedRun, output_manifest: { ...rejectedRun.output_manifest,
        generation_config: { reference_style: "color_redraw", reference_prompt_version: previousVersion },
      } }]);
    return original(input, init);
  });
  renderPage(<StudioPage />, "/studio");
  const button = await screen.findByRole("button", { name: "重新生成" });
  expect(button).toBeEnabled();
  expect(screen.queryByText("暂无可用的图片素材")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("参考图片")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "前往采访添加素材" })).not.toBeInTheDocument();
  fireEvent.click(button);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/v1/production/runs"),
    expect.objectContaining({ method: "POST" })));
  expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).endsWith("/blocked-job/retry"))).toBe(false);
  expect(window.confirm).not.toHaveBeenCalled();
});

test.each(["failed", "completed"])("terminal %s immediately refreshes the frozen wallet", async (status) => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  let balance = -405;
  const running = { ...rejectedRun, status: "running", recovery: null, error_message: null };
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).endsWith("/v1/wallet")) return response({ available_cents: balance,
      prices: { video_billing_mode: "tokens", video_reserve_cents: 2400 } });
    if (String(input).endsWith("/v1/production/runs")) return response([running]);
    return original(input, init);
  });
  const { queryClient } = renderPage(<StudioPage />, "/studio");
  expect(await screen.findByRole("button", { name: "正在生成" })).toBeDisabled();
  balance = 874;
  act(() => queryClient.setQueryData(["production-runs"], [{ ...running, status,
    updated_at: "2026-09-14T01:16:00Z", error_message: status === "failed" ? "VIDEO_PROVIDER_TIMEOUT" : null }]));
  await waitFor(() => expect(screen.getByRole("button", { name: status === "failed" ? "重新生成" : "生成影像" })).toBeEnabled());
  expect(screen.queryByRole("button", { name: "重新尝试" })).not.toBeInTheDocument();
});

test("an updated script can generate after an older version was rejected", async () => {
  mockRecovery();
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) => String(input).endsWith("/v1/scripts")
    ? response([{ ...project, version_number: 2 }]) : original(input, init));
  renderPage(<StudioPage />, "/studio");
  expect(await screen.findByRole("button", { name: "重新生成" })).toBeEnabled();
});
