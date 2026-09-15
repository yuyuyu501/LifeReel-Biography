import type { ProductionRun, ScriptScene, ScriptShot } from "@lifereel/contracts";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ScriptSections } from "./ScriptSections";
import { ProductionDetails } from "./ProductionDetails";

const scene: ScriptScene = {
  id: "scene-1", chapter_id: "chapter-1", order_index: 1, heading: "回家",
  plot: "主人公离乡后第一次回家，与母亲团聚。",
  dialogues: [
    { kind: "narration", speaker: "林奶奶", text: "那年冬天，我回到了家。" },
    { kind: "dialogue", speaker: "母亲", text: "回来就好。" },
  ],
  narration: "那年冬天，我回到了家。\n回来就好。",
  visual_prompt: "冬日的老屋，炉火照亮木桌。", duration_seconds: 20, source_claim_ids: [],
};
const shots: ScriptShot[] = [
  { id: "shot-2", scene_id: scene.id, order_index: 2, shot_type: "closeup",
    visual_prompt: "母亲握住女儿的手。", duration_seconds: 10, source_claim_ids: [] },
  { id: "foreign", scene_id: "scene-2", order_index: 1, shot_type: "wide",
    visual_prompt: "另一章的画面", duration_seconds: 10, source_claim_ids: [] },
  { id: "shot-1", scene_id: scene.id, order_index: 1, shot_type: "wide",
    visual_prompt: "主人公推开家门。", duration_seconds: 10, source_claim_ids: [] },
];

test("renders four distinct sections, ordered chapter shots and attributed spoken lines", () => {
  render(<ScriptSections scene={scene} shots={shots} />);
  expect(screen.getAllByRole("heading", { level: 4 }).map((item) => item.textContent))
    .toEqual(["剧情", "分镜", "人物对话", "场景描述"]);
  expect(within(screen.getByRole("region", { name: "剧情" })).getByText(scene.plot!)).toBeVisible();
  const shotItems = within(screen.getByRole("region", { name: "分镜" })).getAllByRole("listitem");
  expect(shotItems).toHaveLength(2);
  expect(shotItems[0]).toHaveTextContent("主人公推开家门。");
  expect(shotItems[1]).toHaveTextContent("母亲握住女儿的手。");
  expect(screen.queryByText("另一章的画面")).not.toBeInTheDocument();
  const lines = within(screen.getByRole("region", { name: "人物对话" })).getAllByRole("listitem");
  expect(lines[0]).toHaveTextContent("林奶奶旁白那年冬天，我回到了家。");
  expect(lines[1]).toHaveTextContent("母亲对话回来就好。");
  expect(within(screen.getByRole("region", { name: "场景描述" })).getByText(scene.visual_prompt)).toBeVisible();
});

test("legacy records keep narration without inventing missing plot or dialogue", () => {
  render(<ScriptSections scene={{ ...scene, plot: null, dialogues: null }} />);
  expect(screen.getByText("本章尚未记录独立的剧情概述")).toBeVisible();
  expect(screen.getByText("本章尚未记录分镜")).toBeVisible();
  const spoken = screen.getByRole("region", { name: "人物对话" });
  expect(within(spoken).getAllByText("旁白")).toHaveLength(1);
  expect(spoken).toHaveTextContent("那年冬天，我回到了家。");
  expect(within(spoken).queryByText("母亲")).not.toBeInTheDocument();
});

test("uses frozen snapshot shots and exposes actual production prompts as plain text", () => {
  const prompt = "<script>alert('not executable')</script>\n本段实际提示词";
  const { container } = render(<ProductionDetails run={{ output_manifest: {
    script_snapshot: [{ ...scene, shots: [shots[2]] }],
    plan: { continuity: "旧宅冬日", voice: "温和女声" }, segments: [
      { status: "failed", duration_seconds: 10, narration: "本段旁白", visual_prompt: "生成时的镜头", prompt },
    ] } } as ProductionRun} />);
  expect(screen.queryByText(shots[0].visual_prompt)).not.toBeInTheDocument();
  expect(screen.getByText("旧宅冬日")).toBeVisible();
  fireEvent.click(screen.getByText("实际生成提示词"));
  expect(container.querySelector("pre")).toHaveTextContent("本段实际提示词");
  expect(container.querySelector("pre")).toBeVisible();
  expect(container.querySelector("script")).toBeNull();
});
