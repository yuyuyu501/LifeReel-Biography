import type { ScriptProject } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { api } from "../api/client";
import { ApiError } from "../api/errors";
import { EditableScript } from "./EditableScript";

const project = { id: "p1", version_number: 2, shots: [{id: "sh1", scene_id: "s1", order_index: 1,
  shot_type: "wide", visual_prompt: "老屋全景", duration_seconds: 20}], scenes: [{
  id: "s1", heading: "回家", plot: "回家与母亲团聚", narration: "我回到了家。",
  dialogues: null, duration_seconds: 20, visual_prompt: "冬日老屋", source_claim_ids: [],
}] } as unknown as ScriptProject;

function setup() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  client.setQueryData(["scripts"], [project]);
  const changed = vi.fn();
  render(<QueryClientProvider client={client}><EditableScript project={project} scene={project.scenes[0]} onEditingChange={changed} /></QueryClientProvider>);
  return {client, changed};
}

test("pencil opens all four editable parts and saves canonical fields without an AI request", async () => {
  const save = vi.spyOn(api, "updateScriptScene").mockResolvedValue(project);
  const generate = vi.spyOn(api, "generateScript");
  const {changed} = setup();
  fireEvent.click(screen.getByRole("button", {name: "编辑本章剧本"}));
  expect(changed).toHaveBeenCalledWith(true);
  fireEvent.change(screen.getByLabelText("剧情"), {target: {value: "新的剧情概述"}});
  fireEvent.change(screen.getByLabelText("镜头 1 画面与动作"), {target: {value: "慢慢推近炉边"}});
  fireEvent.change(screen.getByLabelText("台词 1 内容"), {target: {value: "那年我第一次回家。"}});
  fireEvent.change(screen.getByLabelText("场景描述"), {target: {value: "冬日厨房，炉火温暖"}});
  fireEvent.click(screen.getByRole("button", {name: "保存修改"}));
  await waitFor(() => expect(save).toHaveBeenCalledWith("p1", "s1", expect.objectContaining({
    expected_version: 2, plot: "新的剧情概述", visual_prompt: "冬日厨房，炉火温暖",
    dialogues: [{kind: "narration", speaker: "旁白", text: "那年我第一次回家。"}],
    shots: [{shot_type: "wide", duration_seconds: 20, visual_prompt: "慢慢推近炉边"}],
  })));
  await waitFor(() => expect(changed).toHaveBeenLastCalledWith(false));
  expect(generate).not.toHaveBeenCalled();
});

test("duration validation, ordered lines, cancellation and conflict preservation", async () => {
  const save = vi.spyOn(api, "updateScriptScene").mockRejectedValue(new ApiError("SCRIPT_EDIT_CONFLICT", 409));
  setup();
  fireEvent.click(screen.getByRole("button", {name: "编辑本章剧本"}));
  fireEvent.change(screen.getByLabelText("镜头 1 时长"), {target: {value: "10"}});
  expect(screen.getByRole("button", {name: "保存修改"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("章节总时长（秒）"), {target: {value: "10"}});
  fireEvent.click(screen.getByRole("button", {name: "添加台词"}));
  fireEvent.change(screen.getByLabelText("台词 2 说话人"), {target: {value: "母亲"}});
  fireEvent.change(screen.getByLabelText("台词 2 内容"), {target: {value: "回来就好。"}});
  fireEvent.click(screen.getByRole("button", {name: "上移台词 2"}));
  expect(screen.getByLabelText("台词 1 说话人")).toHaveValue("母亲");
  fireEvent.click(screen.getByRole("button", {name: "保存修改"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("其他位置更新");
  expect(screen.getByLabelText("台词 1 内容")).toHaveValue("回来就好。");
  expect(save).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", {name: "取消"}));
  expect(screen.queryByLabelText("台词 1 内容")).not.toBeInTheDocument();
});
