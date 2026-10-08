import type {
  InterviewRound,
  ProductionRun,
  ScriptScene,
  ScriptShot,
} from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import { AnswerHistory } from "./InterviewExperience";
import { GettingStarted } from "./GettingStarted";
import { ProductionQuality, ShotPreview } from "./ProductionExperience";
import {
  useConversationFollow,
  useInterviewDraft,
} from "../hooks/useConversationExperience";

function wrap(element: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>{element}</QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

test("shot preview uses ordered project shots belonging to the selected scene", () => {
  render(
    <ShotPreview
      scene={{ id: "scene" } as ScriptScene}
      projectShots={
        [
          {
            id: "second",
            scene_id: "scene",
            order_index: 2,
            visual_prompt: "织布机细节",
            duration_seconds: 6,
            shot_type: "detail",
          },
          {
            id: "other",
            scene_id: "other",
            order_index: 1,
            visual_prompt: "另一章画面",
            duration_seconds: 5,
            shot_type: "wide",
          },
          {
            id: "first",
            scene_id: "scene",
            order_index: 1,
            visual_prompt: "家乡全景",
            duration_seconds: 4,
            shot_type: "wide",
          },
        ] as ScriptShot[]
      }
    />,
  );
  expect(screen.queryByText("分镜尚未生成。")).not.toBeInTheDocument();
  expect(screen.queryByText("另一章画面")).not.toBeInTheDocument();
  const shots = screen.getAllByRole("article");
  expect(shots[0]).toHaveTextContent("家乡全景");
  expect(shots[1]).toHaveTextContent("织布机细节");
});

test("history remains readable without an answer-editing action", () => {
  wrap(
    <AnswerHistory
      round={
        {
          id: "r",
          answer_text: "当前文本",
          answer_revisions: [{ version: 1, text: "历史原文" }],
        } as InterviewRound
      }
    />,
  );
  expect(
    screen.queryByRole("button", { name: /修改/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("查看历史原文")).toBeInTheDocument();
  expect(screen.getByText("历史原文")).toBeInTheDocument();
});

test("drafts remain isolated across chapters and recover when revisiting", () => {
  function Draft({ id }: { id: string }) {
    const [value, set] = useInterviewDraft(id);
    return (
      <input
        aria-label="草稿"
        value={value}
        onChange={(e) => set(e.target.value)}
      />
    );
  }
  const first = render(<Draft key="one" id="one" />);
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "第一章未发内容" },
  });
  first.rerender(<Draft key="two" id="two" />);
  expect(screen.getByRole("textbox")).toHaveValue("");
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "第二章草稿" },
  });
  first.rerender(<Draft key="one" id="one" />);
  expect(screen.getByRole("textbox")).toHaveValue("第一章未发内容");
});

test("history reading retains scroll position and exposes a return-to-latest action", () => {
  function Conversation({ message }: { message: string }) {
    const follow = useConversationFollow(message);
    return (
      <>
        <div
          data-testid="conversation"
          ref={follow.conversation}
          onScroll={follow.onScroll}
        >
          {message}
        </div>
        {follow.unread && <button onClick={follow.showLatest}>回到最新</button>}
      </>
    );
  }
  const view = render(<Conversation message="first" />);
  const area = screen.getByTestId("conversation");
  Object.defineProperties(area, {
    scrollHeight: { value: 1000, configurable: true },
    clientHeight: { value: 200 },
  });
  area.scrollTop = 100;
  fireEvent.scroll(area);
  view.rerender(<Conversation message="second" />);
  expect(area.scrollTop).toBe(100);
  fireEvent.click(screen.getByRole("button", { name: "回到最新" }));
  expect(area.scrollTop).toBe(1000);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("guide can be closed, resumed and reopened without storing personal content", () => {
  const view = wrap(<GettingStarted userId="one" />);
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
  fireEvent.click(screen.getByRole("button", { name: "暂时收起" }));
  view.unmount();
  wrap(<GettingStarted userId="one" />);
  fireEvent.click(screen.getByRole("button", { name: "重新打开使用教学" }));
  expect(screen.getByRole("heading", { name: "从一句话开始" })).toBeVisible();
  expect(JSON.parse(localStorage.getItem("lifereel:guide:v2:one")!)).toEqual({
    step: 1,
    hidden: false,
  });
});

test("local regeneration shows a quote before submitting and targets only the chosen shot", async () => {
  vi.spyOn(api, "segmentQuote").mockResolvedValue({
    amount_cents: 300,
    target_seconds: 5,
    video_billing_mode: "per_second",
    script_version: 3,
  });
  const regenerate = vi
    .spyOn(api, "regenerateSegment")
    .mockResolvedValue({ id: "new" } as ProductionRun);
  const run = {
    id: "run",
    status: "completed",
    output_manifest: {
      generation_config: { mode: "segmented" },
      segments: [
        {
          status: "completed",
          duration_seconds: 5,
          narration: "说明",
          visual_prompt: "城市远景",
          review_frames: [{ position: 0, at_seconds: 1 }],
        },
      ],
    },
  } as ProductionRun;
  wrap(<ProductionQuality run={run} />);
  expect(screen.getByRole("img")).toHaveAttribute(
    "src",
    expect.stringContaining("/runs/run/segments/0/review/0"),
  );
  fireEvent.click(screen.getByRole("button", { name: "重做第 1 镜头" }));
  await screen.findByText(/本镜头费用/);
  expect(regenerate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认重做" }));
  await waitFor(() =>
    expect(regenerate).toHaveBeenCalledWith(
      "run",
      0,
      expect.objectContaining({
        quoted_amount_cents: 300,
        expected_script_version: 3,
      }),
    ),
  );
});
