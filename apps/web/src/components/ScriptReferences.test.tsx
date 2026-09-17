import type { ScriptProject, SourceAsset } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, vi } from "vitest";
import { api } from "../api/client";
import { ScriptReferences } from "./ScriptReferences";

const photo = { id: "photo", subject_id: "subject", kind: "photo", original_filename: "本章照片.png", mime_type: "image/png", byte_size: 100, status: "ready", consent_status: "granted" } as SourceAsset;
const sound = { ...photo, id: "sound", kind: "audio", mime_type: "audio/wav", original_filename: "声音.wav" };
const project = { id: "project", subject_id: "subject", version_number: 3, scenes: [{id: "scene", reference_asset_ids: null}] } as unknown as ScriptProject;
beforeEach(() => {
  vi.spyOn(api, "scriptReferences").mockResolvedValue([photo]);
  vi.spyOn(api, "listEvidence").mockResolvedValue([photo, sound, {...photo, id: "foreign", subject_id: "other", original_filename: "其他人的.png"}]);
  vi.spyOn(api, "updateScriptReferences").mockResolvedValue({...project, version_number: 4});
});
function setup() {
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}});
  render(<QueryClientProvider client={client}><ScriptReferences project={project} scene={project.scenes[0]} /></QueryClientProvider>);
}
test("shows automatic references and saves an explicit empty selection", async () => {
  setup();
  expect(await screen.findByRole("img", {name: "本章照片.png"})).toBeVisible();
  fireEvent.click(screen.getByRole("button", {name:"编辑本章形象"}));
  fireEvent.click(await screen.findByRole("checkbox", {name:"本章照片.png"}));
  expect(screen.queryByRole("checkbox", {name:"其他人的.png"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:"保存"}));
  await waitFor(() => expect(api.updateScriptReferences).toHaveBeenCalledWith("project", "scene", 3, []));
});
test("allows audio alongside the image and keeps an empty chapter empty", async () => {
  vi.mocked(api.scriptReferences).mockResolvedValue([]);
  setup();
  await waitFor(() => expect(screen.getByRole("button", {name:"编辑本章形象"})).toBeEnabled());
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:"编辑本章形象"}));
  fireEvent.click(await screen.findByRole("checkbox", {name:"声音.wav"}));
  expect(screen.getByText("音频参考需搭配至少一张图片。")).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox", {name:"本章照片.png"}));
  expect(screen.queryByText("音频参考需搭配至少一张图片。")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name:"保存"}));
  await waitFor(() => expect(api.updateScriptReferences).toHaveBeenCalledWith("project", "scene", 3, ["sound", "photo"]));
});
