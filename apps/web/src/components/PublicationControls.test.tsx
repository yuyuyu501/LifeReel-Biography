import type { ConsentGrant, Person, Publication } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import { PublicationControls } from "./PublicationControls";

const person = {
  id: "person",
  display_name: "陈阿姨",
  is_minor: false,
} as Person;
const grant: ConsentGrant = {
  id: "grant",
  subject_id: person.id,
  consent_type: "publication",
  scope: "family",
  status: "granted",
  granted_by: "陈阿姨本人",
  evidence_note: null,
  expires_at: null,
  created_at: "2026-11-01T00:00:00Z",
};
const publication = {
  id: "publication",
  production_run_id: "run",
  access_token: "share-token",
  subject_id: person.id,
  audience: "family",
  status: "published",
} as Publication;

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listConsents").mockResolvedValue([]);
  vi.spyOn(api, "createConsent").mockResolvedValue(grant);
  vi.spyOn(api, "publish").mockResolvedValue(publication);
  vi.spyOn(api, "withdrawPublication").mockResolvedValue({
    ...publication,
    status: "withdrawn",
  });
  vi.spyOn(api, "revokeConsent").mockResolvedValue({
    ...grant,
    status: "revoked",
  });
});

function show(published = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <PublicationControls
        runId="run"
        person={person}
        publication={published ? publication : undefined}
      />
    </QueryClientProvider>,
  );
}

test("requires explicit confirmation and authorization before publishing", async () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "发布给家人" }));
  const button = await screen.findByRole("button", { name: "确认授权并发布" });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("授权人姓名"), {
    target: { value: "陈阿姨本人" },
  });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() =>
    expect(api.publish).toHaveBeenCalledWith("run", "family"),
  );
  expect(api.createConsent).toHaveBeenCalledWith(
    expect.objectContaining({
      subject_id: "person",
      granted_by: "陈阿姨本人",
      consent_type: "publication",
      scope: "family",
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
});

test("publication failure retains the dialog and reuses the saved consent on retry", async () => {
  let saved = false;
  vi.mocked(api.listConsents).mockImplementation(async () =>
    saved ? [grant] : [],
  );
  vi.mocked(api.createConsent).mockImplementation(async () => {
    saved = true;
    return grant;
  });
  vi.mocked(api.publish).mockRejectedValueOnce(new Error("网络暂时中断"));
  show();
  fireEvent.click(screen.getByRole("button", { name: "发布给家人" }));
  fireEvent.change(await screen.findByLabelText("授权人姓名"), {
    target: { value: "陈阿姨本人" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "确认授权并发布" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "操作失败，请稍后重试。",
  );
  fireEvent.click(screen.getByRole("button", { name: "确认授权并发布" }));
  await waitFor(() => expect(api.publish).toHaveBeenCalledTimes(2));
  expect(api.createConsent).toHaveBeenCalledTimes(1);
});

test("shows the real link, withdraws publication and confirms grant revocation", async () => {
  vi.mocked(api.listConsents).mockResolvedValue([grant]);
  show(true);
  expect(screen.getByLabelText("家人分享链接")).toHaveValue(
    `${window.location.origin}/watch/share-token`,
  );
  fireEvent.click(screen.getByRole("button", { name: "撤回发布" }));
  await waitFor(() =>
    expect(api.withdrawPublication).toHaveBeenCalledWith(
      "publication",
      expect.anything(),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "管理发布授权" }));
  fireEvent.click(await screen.findByRole("button", { name: "撤销这份授权" }));
  expect(api.revokeConsent).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认撤销" }));
  await waitFor(() =>
    expect(api.revokeConsent).toHaveBeenCalledWith("grant", expect.anything()),
  );
});

test("failed consent loading cannot be treated as permission to publish", async () => {
  vi.mocked(api.listConsents).mockRejectedValue(new Error("授权读取失败"));
  show();
  fireEvent.click(screen.getByRole("button", { name: "发布给家人" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("内容加载失败");
  expect(
    screen.queryByRole("button", { name: "确认授权并发布" }),
  ).not.toBeInTheDocument();
  expect(api.createConsent).not.toHaveBeenCalled();
});
