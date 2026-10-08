import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { InterviewsPage } from "./InterviewsPage";

const person = {
  id: "person-1",
  display_name: "林秀兰",
  preferred_name: "林奶奶",
  is_subject: true,
};
const second = {
  ...person,
  id: "person-2",
  display_name: "王叔叔",
  preferred_name: "王叔叔",
};
const profile = {
  id: "profile-1",
  subject_id: person.id,
  version_number: 1,
  template_version: "test",
  sections: [{ key: "A", title: "基本信息" }],
  fields: [
    {
      key: "identity.preferred_name",
      label: "书中称呼",
      priority: "基础",
      section: "A",
      question: "怎样称呼？",
    },
  ],
  entries: [
    {
      id: "entry-1",
      field_key: "identity.preferred_name",
      record_key: "single",
      value: "林奶奶",
      state: "filled",
      certainty: "reported",
      use_scope: "works",
      source: { type: "person" },
      version_number: 1,
    },
  ],
  readiness: {
    status: "not_ready",
    processed_fields: 1,
    total_fields: 67,
    message: "仍需具体经历",
    missing_fields: [],
    themes: [],
  },
};
const history = {
  id: "legacy-1",
  subject_id: person.id,
  chapter_id: "chapter-1",
  started_at: "2026-09-07T00:00:00Z",
};
function response(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response;
}
function page() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <MemoryRouter initialEntries={["/interviews"]}>
        <Routes>
          <Route path="/interviews" element={<InterviewsPage />} />
          <Route path="/interviews/:id" element={<p>已进入资料采访</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split("?")[0];
      if (path.endsWith("/v1/persons")) return response([person, second]);
      if (path.endsWith("/v1/interviews")) return response([history]);
      if (path.endsWith("/subjects/person-1")) return response(profile);
      if (path.endsWith("/subjects/person-2"))
        return response({
          ...profile,
          id: "profile-2",
          subject_id: second.id,
          entries: [{ ...profile.entries[0], value: "王叔叔" }],
        });
      return response([]);
    }),
  );
});
test("uses one life profile and opens an interview without a chapter", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) =>
    init?.method === "POST"
      ? response({ id: "life-session" })
      : original(input, init),
  );
  page();
  await screen.findByText("人生资料表");
  fireEvent.click(screen.getByRole("button", { name: "开始或继续采访" }));
  expect(await screen.findByText("已进入资料采访")).toBeInTheDocument();
  const sent = vi
    .mocked(fetch)
    .mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(JSON.parse(String(sent[1]?.body))).toEqual({ subject_id: person.id });
});
test("switching people loads their own life profile", async () => {
  page();
  await screen.findByText("人生资料表");
  expect(screen.getByText("林奶奶", { selector: "p" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("采访人物"), {
    target: { value: second.id },
  });
  await waitFor(() =>
    expect(screen.getByText("王叔叔", { selector: "p" })).toBeInTheDocument(),
  );
  expect(
    screen.queryByText("林奶奶", { selector: "p" }),
  ).not.toBeInTheDocument();
});
test("retains historical interview links without chapter gates", async () => {
  page();
  await screen.findByText("人生资料表");
  fireEvent.click(screen.getByText("查看以前的采访记录"));
  expect(screen.getByRole("link", { name: /历史对话/ })).toHaveAttribute(
    "href",
    "/interviews/legacy-1",
  );
  expect(screen.queryByText("章节采访")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /前往写书/ })).toBeInTheDocument();
});
