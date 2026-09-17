import type { Job, SourceAsset } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import { PhotoRedraw } from "./PhotoRedraw";

const asset: SourceAsset = {
  id: "source",
  subject_id: "subject",
  interview_session_id: null,
  kind: "photo",
  original_filename: "portrait.png",
  mime_type: "image/png",
  byte_size: 100,
  sha256: "source-hash",
  status: "ready",
  consent_scope: "private",
  consent_status: "granted",
  created_at: "2026-09-17T00:00:00Z",
  captured_at: "2026-09-17T00:00:00Z",
};
const job: Job = {
  id: "redraw-job",
  kind: "evidence.photo_redraw",
  status: "queued",
  idempotency_key: "key",
  payload: {},
  result: null,
  error_code: null,
  error_message: null,
  attempt_count: 0,
  created_at: "2026-09-17T00:00:00Z",
  updated_at: "2026-09-17T00:00:00Z",
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "photoRedrawStatus").mockResolvedValue({
    enabled: true,
    job: null,
  });
  vi.spyOn(api, "redrawPhoto").mockResolvedValue(job);
  vi.spyOn(api, "retryJob").mockResolvedValue(job);
});

function setup(source = asset) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onStart = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <PhotoRedraw asset={source} onStart={onStart} />
    </QueryClientProvider>,
  );
  return { queryClient, onStart };
}

test("requests once, shows progress, restores completed result and switches to original", async () => {
  const { queryClient, onStart } = setup();
  const button = screen.getByRole("button", { name: "添加标注" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  expect(
    await screen.findByRole("button", { name: "等待标注" }),
  ).toBeDisabled();
  expect(api.redrawPhoto).toHaveBeenCalledExactlyOnceWith("source");
  expect(onStart).toHaveBeenCalledOnce();
  vi.mocked(api.photoRedrawStatus).mockResolvedValue({
    enabled: true,
    job: { ...job, status: "completed", result: { asset_id: "redrawn" } },
  });
  await act(() =>
    queryClient.invalidateQueries({ queryKey: ["photo-redraw", asset.id] }),
  );
  expect(
    await screen.findByRole("img", { name: "portrait.png 标注图" }),
  ).toHaveAttribute("src", "/v1/evidence/assets/redrawn/content");
  fireEvent.click(screen.getByRole("button", { name: "原图" }));
  expect(screen.getByRole("img", { name: "portrait.png" })).toHaveAttribute(
    "src",
    "/v1/evidence/assets/source/content",
  );
  expect(screen.getByRole("link", { name: "打开标注图片" })).toHaveAttribute(
    "href",
    "/v1/evidence/assets/redrawn/content",
  );
});

test("explicitly retries interrupted work and displays the possible extra charge", async () => {
  vi.mocked(api.photoRedrawStatus).mockResolvedValue({
    enabled: true,
    job: {
      ...job,
      status: "failed",
      attempt_count: 1,
      error_code: "PHOTO_REDRAW_UNCERTAIN",
    },
  });
  setup();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "可能产生新的费用",
  );
  fireEvent.click(screen.getByRole("button", { name: "重新标注" }));
  await waitFor(() =>
    expect(api.retryJob).toHaveBeenCalledExactlyOnceWith("redraw-job"),
  );
  expect(api.redrawPhoto).not.toHaveBeenCalled();
});

test("does not retry a provider rejection", async () => {
  vi.mocked(api.photoRedrawStatus).mockResolvedValue({
    enabled: true,
    job: {
      ...job,
      status: "failed",
      attempt_count: 1,
      error_code: "PHOTO_REDRAW_REJECTED",
    },
  });
  setup();
  expect(await screen.findByRole("alert")).toHaveTextContent("未接受");
  expect(screen.getByRole("button", { name: "添加标注" })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "重新标注" }),
  ).not.toBeInTheDocument();
});

test("disabled deployment cannot start paid work", async () => {
  vi.mocked(api.photoRedrawStatus).mockResolvedValue({
    enabled: false,
    job: null,
  });
  setup();
  expect(await screen.findByText("暂未启用")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "添加标注" })).toBeDisabled();
});

test("derived photos are labelled and cannot be submitted again", () => {
  setup({ ...asset, is_redraw: true, derived_from_asset_id: "original" });
  expect(screen.getByText("AI 处理图片")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "添加标注" }),
  ).not.toBeInTheDocument();
  expect(api.photoRedrawStatus).not.toHaveBeenCalled();
});
