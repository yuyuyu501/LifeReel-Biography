import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import type { PhotoRestoration } from "../api/client";
import { PhotoRestorationPage } from "./PhotoRestorationPage";

const photo = {
  id: "photo",
  original_filename: "旧照片.png",
  mime_type: "image/png",
  byte_size: 123,
  created_at: "2026-09-18T00:00:00Z",
};
const run: PhotoRestoration = {
  id: "restore",
  photo,
  status: "completed",
  colorize: false,
  error_code: null,
  can_retry: false,
  created_at: photo.created_at,
};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "restorationSettings").mockResolvedValue({
    enabled: true,
    max_bytes: 10485760,
  });
  vi.spyOn(api, "restorationHistory").mockResolvedValue({
    items: [],
    page: 1,
    total: 0,
    page_size: 12,
  });
  vi.spyOn(api, "uploadRestorationPhoto").mockResolvedValue(photo);
  vi.spyOn(api, "startRestoration").mockResolvedValue({
    ...run,
    status: "queued",
  });
  vi.spyOn(api, "restorationRun").mockResolvedValue(run);
  vi.spyOn(api, "retryJob").mockResolvedValue({} as never);
});
function setup() {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={cache}>
      <MemoryRouter>
        <PhotoRestorationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { cache, ...view };
}
test("uploads without a person and calls the model only when start is clicked", async () => {
  setup();
  await screen.findByText("暂无修复记录");
  expect(screen.getByRole("checkbox", { name: "上色" })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "开始修复" })).toBeDisabled();
  const file = new File(["photo"], "old.png", { type: "image/png" });
  fireEvent.change(screen.getByLabelText("上传老照片"), {
    target: { files: [file] },
  });
  await screen.findByRole("img", { name: photo.original_filename });
  expect(api.uploadRestorationPhoto).toHaveBeenCalledExactlyOnceWith(file);
  expect(api.startRestoration).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "开始修复" }));
  await waitFor(() =>
    expect(api.startRestoration).toHaveBeenCalledExactlyOnceWith(
      "photo",
      false,
    ),
  );
});
test("history restores comparison, zoom, download, and an explicit save", async () => {
  vi.mocked(api.restorationHistory).mockResolvedValue({
    items: [run],
    total: 1,
    page: 1,
    page_size: 12,
  });
  vi.spyOn(api, "listPersons").mockResolvedValue([
    { id: "person", display_name: "家人" },
  ] as never);
  vi.spyOn(api, "saveRestoration").mockResolvedValue({ id: "saved" } as never);
  setup();
  fireEvent.click(
    await screen.findByRole("button", { name: /旧照片.png.*保守修复/ }),
  );
  const slider = await screen.findByRole("slider", { name: "修复前后对比" });
  fireEvent.change(slider, { target: { value: "25" } });
  expect(screen.getByRole("img", { name: "旧照片.png 修复前" })).toHaveStyle({
    clipPath: "inset(0 75% 0 0)",
  });
  fireEvent.click(screen.getByRole("button", { name: "放大照片" }));
  expect(screen.getByLabelText("缩放比例")).toHaveTextContent("150%");
  expect(screen.getByRole("link", { name: "下载" })).toHaveAttribute(
    "href",
    "/v1/photo-restoration/runs/restore/content?download=true",
  );
  expect(api.saveRestoration).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "保存到人物素材" }));
  await screen.findByRole("option", { name: "家人" });
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "person" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await screen.findByText("已保存到人物素材");
  expect(api.saveRestoration).toHaveBeenCalledExactlyOnceWith(
    "restore",
    "person",
  );
});
test("restores running progress and blocks repeated submissions", async () => {
  const running = { ...run, status: "running" };
  vi.mocked(api.restorationHistory).mockResolvedValue({
    items: [running],
    total: 1,
    page: 1,
    page_size: 12,
  });
  vi.mocked(api.restorationRun).mockResolvedValue(running);
  const { cache } = setup();
  fireEvent.click(
    await screen.findByRole("button", { name: /旧照片.png.*正在修复/ }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "正在修复" })).toBeDisabled(),
  );
  expect(screen.getByRole("checkbox")).toBeDisabled();
  await act(() => cache.setQueryData(["restoration", "restore"], run));
  expect(await screen.findByRole("link", { name: "下载" })).toBeVisible();
  expect(api.startRestoration).not.toHaveBeenCalled();
});
test("invalid files never upload", async () => {
  setup();
  fireEvent.change(screen.getByLabelText("上传老照片"), {
    target: {
      files: [new File(["pdf"], "file.pdf", { type: "application/pdf" })],
    },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("10 MB");
  expect(api.uploadRestorationPhoto).not.toHaveBeenCalled();
});
