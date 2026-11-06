import type { ScriptProject } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../api/client";
import { ScriptPlanSummary } from "./ScriptPlanSummary";

const project = {
  adaptation_brief: {
    theme: "巷口的童年",
    intended_audience: "family",
    dramatic_question: "这段经历留下了什么？",
    time_scope: null,
    must_include: [],
    must_avoid: ["不使用可辨识正脸"],
    tone: "克制",
    source_revision_ids: ["revision-1"],
  },
  story_bible: {
    characters: [],
    locations: [],
    timeline: [],
    key_objects: [],
    constraints: ["保持年代一致"],
    source_revision_ids: ["revision-1"],
  },
  sequence_plan: {
    items: [
      {
        key: "opening",
        order_index: 1,
        title: "巷口",
        narrative_role: "opening",
        summary: "从童年生活展开。",
        source_revision_ids: ["revision-1"],
      },
    ],
  },
} as unknown as ScriptProject;

test("renders the saved adaptation planning artifacts", () => {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <ScriptPlanSummary project={project} />
    </QueryClientProvider>,
  );
  expect(screen.getByText("改编规划", { selector: "summary" })).toBeVisible();
  fireEvent.click(screen.getByText("改编规划", { selector: "summary" }));
  expect(screen.getByText("巷口的童年")).toBeVisible();
  expect(screen.getByText("1. 巷口")).toBeVisible();
  expect(screen.getByText("开场")).toBeVisible();
  expect(screen.getByText("连续性约束：保持年代一致")).toBeVisible();
});

test("does not render for legacy projects without planning artifacts", () => {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <ScriptPlanSummary project={{} as ScriptProject} />
    </QueryClientProvider>,
  );
  expect(screen.queryByText("改编规划")).not.toBeInTheDocument();
});

test("edits the plan and saves a reordered sequence with the current version", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const editableProject = {
    ...project,
    id: "project-1",
    version_number: 4,
    sequence_plan: {
      items: [
        ...project.sequence_plan!.items,
        {
          key: "closing",
          order_index: 2,
          title: "回望",
          narrative_role: "closing",
          summary: "回望这段经历。",
          source_revision_ids: ["revision-1"],
        },
      ],
    },
  } as ScriptProject;
  client.setQueryData(["scripts"], [editableProject]);
  const save = vi
    .spyOn(api, "updateScriptAdaptationPlan")
    .mockResolvedValue(editableProject);
  render(
    <QueryClientProvider client={client}>
      <ScriptPlanSummary project={editableProject} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText("改编规划", { selector: "summary" }));
  fireEvent.click(screen.getByRole("button", { name: "编辑改编规划" }));
  fireEvent.change(screen.getByLabelText("核心主题"), {
    target: { value: "从巷口走向远方" },
  });
  fireEvent.click(screen.getByRole("button", { name: "下移场次 1" }));
  fireEvent.click(screen.getByRole("button", { name: "保存规划" }));
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(
      "project-1",
      expect.objectContaining({
        expected_version: 4,
        adaptation_brief: expect.objectContaining({
          theme: "从巷口走向远方",
        }),
        sequence_plan: {
          items: expect.arrayContaining([
            expect.objectContaining({ key: "closing", order_index: 1 }),
            expect.objectContaining({ key: "opening", order_index: 2 }),
          ]),
        },
      }),
    ),
  );
});
