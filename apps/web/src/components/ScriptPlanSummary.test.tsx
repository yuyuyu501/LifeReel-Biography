import type { ScriptProject } from "@lifereel/contracts";
import { fireEvent, render, screen } from "@testing-library/react";
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
    items: [{
      key: "opening",
      order_index: 1,
      title: "巷口",
      narrative_role: "opening",
      summary: "从童年生活展开。",
      source_revision_ids: ["revision-1"],
    }],
  },
} as unknown as ScriptProject;

test("renders the saved adaptation planning artifacts", () => {
  render(<ScriptPlanSummary project={project} />);
  expect(screen.getByText("改编规划")).toBeVisible();
  fireEvent.click(screen.getByText("改编规划"));
  expect(screen.getByText("巷口的童年")).toBeVisible();
  expect(screen.getByText("1. 巷口")).toBeVisible();
  expect(screen.getByText("开场")).toBeVisible();
  expect(screen.getByText("连续性约束：保持年代一致")).toBeVisible();
});

test("does not render for legacy projects without planning artifacts", () => {
  render(<ScriptPlanSummary project={{} as ScriptProject} />);
  expect(screen.queryByText("改编规划")).not.toBeInTheDocument();
});
