import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
        <InterviewsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split("?")[0];
      if (path.endsWith("/v1/persons")) return response([person, second]);
      if (path.endsWith("/v1/interviews") && init?.method === "POST") {
        const id = JSON.parse(String(init.body)).subject_id;
        return response({ id: `session-${id}` });
      }
      if (path.endsWith("/workspace")) {
        const isSecond = path.includes("session-person-2");
        const subject = isSecond ? second : person;
        return response({
          session: {
            id: `session-${subject.id}`,
            subject_id: subject.id,
            rounds: [
              {
                id: "opening",
                question_text: `${subject.preferred_name}，您想从哪段经历说起？`,
              },
            ],
          },
          profile: isSecond
            ? {
                ...profile,
                id: "profile-2",
                subject_id: second.id,
                entries: [{ ...profile.entries[0], value: "王叔叔" }],
              }
            : profile,
          assets: [],
          script: null,
          latest_workflow: null,
        });
      }
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
test("opens the AI conversation and editable profile together without a chapter", async () => {
  page();
  await screen.findByRole("heading", { name: "人生资料表" });
  expect(
    screen.getByRole("textbox", { name: "说说这段往事" }),
  ).toBeInTheDocument();
  expect(screen.getByText("林奶奶，您想从哪段经历说起？")).toBeInTheDocument();
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
test("removes the old interview entry while preserving AI interviewing and book navigation", async () => {
  page();
  await screen.findByText("人生资料表");
  expect(screen.queryByText("查看以前的采访记录")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: /历史对话/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "AI 采访" })).toBeInTheDocument();
  expect(screen.queryByText("章节采访")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /前往写书/ })).toBeInTheDocument();
});
test("keeps the interview draft when changing people and returning", async () => {
  page();
  const input = await screen.findByRole("textbox", { name: "说说这段往事" });
  fireEvent.change(input, { target: { value: "还没发送的往事" } });
  fireEvent.change(screen.getByLabelText("采访人物"), {
    target: { value: second.id },
  });
  await screen.findByText("王叔叔，您想从哪段经历说起？");
  expect(screen.getByRole("textbox", { name: "说说这段往事" })).toHaveValue("");
  fireEvent.change(screen.getByLabelText("采访人物"), {
    target: { value: person.id },
  });
  await screen.findByText("林奶奶，您想从哪段经历说起？");
  expect(screen.getByRole("textbox", { name: "说说这段往事" })).toHaveValue(
    "还没发送的往事",
  );
});
