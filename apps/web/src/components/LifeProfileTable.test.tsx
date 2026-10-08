import type { LifeProfile, ProfileEntry } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { LifeProfileTable } from "./LifeProfileTable";
import { profilesApi } from "../api/profiles";

vi.mock("../api/profiles", () => ({
  profilesApi: {
    patch: vi.fn(),
    history: vi.fn().mockResolvedValue([]),
    exportUrl: vi.fn().mockReturnValue("/export"),
  },
}));

const entry = (
  id: string,
  field: string,
  value: string,
  extra: Partial<ProfileEntry> = {},
): ProfileEntry => ({
  id,
  field_key: field,
  record_key: id,
  value,
  state: "filled",
  certainty: "reported",
  use_scope: "works",
  source: { type: "manual" },
  version_number: 1,
  ...extra,
});
const profile: LifeProfile = {
  id: "profile-1",
  subject_id: "person-1",
  template_version: "test",
  version_number: 1,
  sections: [
    { key: "A", title: "基本信息" },
    { key: "B", title: "重要经历" },
  ],
  fields: [
    {
      key: "name",
      label: "书中称呼",
      section: "A",
      kind: "text",
      priority: "基础",
      question: "如何称呼？",
    },
    {
      key: "birth",
      label: "出生时间",
      section: "A",
      kind: "text",
      priority: "可选",
      question: "出生在哪一年？",
    },
    {
      key: "family",
      label: "家庭",
      section: "A",
      kind: "text",
      priority: "可选",
      question: "说说家人？",
    },
    {
      key: "work.events[]",
      label: "工作经历",
      section: "B",
      kind: "events",
      priority: "建议",
      question: "说说工作？",
    },
  ],
  entries: [
    entry("name-1", "name", "合成人物"),
    entry("family-1", "family", "", { state: "declined" }),
    entry("work-1", "work.events[]", "时间记不清，需要核实", {
      certainty: "disputed",
      use_scope: "internal",
      source: { type: "manual", quote: "大约是那年夏天" },
    }),
    entry("work-2", "work.events[]", "已确认的第二段经历", {
      certainty: "confirmed",
    }),
  ],
  readiness: {
    status: "not_ready",
    profile_version: 1,
    rule_version: "test",
    scope: "all",
    processed_fields: 3,
    total_fields: 4,
    usable_entries: 2,
    message: "仍需补充具体经历",
    themes: [],
    missing_fields: [],
  },
};

beforeEach(() => {
  vi.mocked(profilesApi.patch).mockReset().mockResolvedValue(profile);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })),
  );
});
function table(data = profile) {
  const onTalk = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = (current: LifeProfile) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LifeProfileTable profile={current} onTalk={onTalk} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(view(data));
  return {
    onTalk,
    update: (current: LifeProfile) => result.rerender(view(current)),
  };
}

test("missing and category filters remain usable without a confirmation status filter", async () => {
  table();
  fireEvent.click(screen.getByRole("button", { name: /^待补充/ }));
  expect(screen.getByText("出生时间")).toBeInTheDocument();
  expect(screen.queryByText("家庭")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^待确认/ }),
  ).not.toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole("button", { name: "筛选分类" }), {
    key: "ArrowDown",
  });
  fireEvent.click(
    await screen.findByRole("menuitemradio", { name: "基本信息" }),
  );
  expect(screen.getByText("出生时间")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^全部/ }));
  expect(screen.getByText("合成人物")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "清除分类筛选" }));
  expect(screen.getByRole("button", { name: "筛选分类" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
});

test("records and editors show content without metadata controls or information icons", () => {
  table();
  for (const text of [
    "来源",
    "状态",
    "使用范围",
    "已有资料",
    "明确陈述",
    "内部资料",
    "人物档案",
    "大约是那年夏天",
  ]) {
    expect(screen.queryByText(text)).not.toBeInTheDocument();
  }
  expect(
    screen.queryByRole("button", { name: /来源与权限/, hidden: true }),
  ).not.toBeInTheDocument();
  const row = screen.getByText("书中称呼").closest(".profile-field")!;
  fireEvent.click(
    within(row as HTMLElement).getByRole("button", { name: "编辑资料" }),
  );
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByText("处理状态")).not.toBeInTheDocument();
  expect(screen.queryByText("确定性")).not.toBeInTheDocument();
  expect(screen.queryByText("化名替换")).not.toBeInTheDocument();
});

test("filtered fields still support interviewing and editing, with filters locked while editing", () => {
  const { onTalk } = table();
  fireEvent.click(screen.getByRole("button", { name: /^待补充/ }));
  fireEvent.click(screen.getByRole("button", { name: "在聊天中补充" }));
  expect(onTalk).toHaveBeenCalledWith(profile.fields[1]);
  fireEvent.click(screen.getByRole("button", { name: "填写" }));
  const form = screen.getByRole("form", { name: "编辑出生时间" });
  expect(form.closest(".profile-field")).toBe(
    screen.getByText("出生时间").closest(".profile-field"),
  );
  expect(form.closest(".profile-section")).not.toBeNull();
  expect(screen.getByRole("button", { name: "筛选分类" })).toBeDisabled();
  expect(screen.getByRole("button", { name: /^全部/ })).toBeDisabled();
  fireEvent.click(within(form).getByRole("button", { name: "取消" }));
  expect(screen.getByRole("button", { name: "筛选分类" })).toBeEnabled();
});

test("editing a disputed or declined entry saves the corrected content and preserves its privacy", async () => {
  const data = {
    ...profile,
    entries: [
      entry("name-1", "name", "旧称呼", {
        state: "declined",
        certainty: "disputed",
        use_scope: "pseudonym",
        pseudonyms: { 旧称呼: "化名" },
      }),
    ],
  };
  table(data);
  fireEvent.click(screen.getByRole("button", { name: "编辑资料" }));
  const form = screen.getByRole("form", { name: "编辑书中称呼" });
  expect(form.closest(".profile-record")).not.toBeNull();
  fireEvent.change(within(form).getByRole("textbox"), {
    target: { value: "新称呼" },
  });
  fireEvent.click(within(form).getByRole("button", { name: "保存资料" }));
  await waitFor(() => expect(profilesApi.patch).toHaveBeenCalledOnce());
  expect(vi.mocked(profilesApi.patch).mock.calls[0][2]).toEqual([
    expect.objectContaining({
      value: "新称呼",
      state: "filled",
      certainty: "reported",
      use_scope: "pseudonym",
      pseudonyms: { 旧称呼: "化名" },
    }),
  ]);
  await waitFor(() =>
    expect(screen.queryByRole("form")).not.toBeInTheDocument(),
  );
});

test("list edits stay on the selected record, additions follow existing records and preserve event structure", async () => {
  const data = {
    ...profile,
    entries: [
      entry("work-1", "work.events[]", "", {
        value: {
          what: "旧经历",
          action: "我参加了工作",
          impact: "学会独立",
          event_id: "event-1",
        },
      }),
      profile.entries[3],
    ],
  };
  table(data);
  fireEvent.click(screen.getByText("重要经历"));
  const row = screen
    .getByText("工作经历")
    .closest(".profile-field") as HTMLElement;
  fireEvent.click(within(row).getAllByRole("button", { name: "编辑资料" })[0]);
  const form = within(row).getByRole("form");
  expect(row.querySelector(".profile-record")?.contains(form)).toBe(true);
  expect(within(form).queryByText("补充内容")).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("发生了什么"), {
    target: { value: "更正的完整经历" },
  });
  fireEvent.click(within(form).getByRole("button", { name: "保存资料" }));
  await waitFor(() => expect(profilesApi.patch).toHaveBeenCalledOnce());
  expect(vi.mocked(profilesApi.patch).mock.calls[0][2][0].value).toEqual({
    what: "更正的完整经历",
    action: "我参加了工作",
    impact: "学会独立",
    event_id: "event-1",
  });
  await waitFor(() =>
    expect(screen.queryByRole("form")).not.toBeInTheDocument(),
  );
  fireEvent.click(within(row).getByRole("button", { name: "添加一条" }));
  const added = within(row).getByRole("form");
  expect(row.querySelectorAll(".profile-record")[2].contains(added)).toBe(true);
  expect(within(added).getByLabelText("发生了什么")).toHaveValue("");
  fireEvent.click(within(added).getByRole("button", { name: "取消" }));
  expect(row.querySelectorAll(".profile-record")).toHaveLength(2);
});

test("failed saves retain the inline draft for retry and cancel leaves original content intact", async () => {
  vi.mocked(profilesApi.patch).mockRejectedValueOnce(
    new Error("保存失败，请重试"),
  );
  table();
  const row = screen
    .getByText("书中称呼")
    .closest(".profile-field") as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { name: "编辑资料" }));
  const form = within(row).getByRole("form");
  fireEvent.change(within(form).getByRole("textbox"), {
    target: { value: "保留草稿" },
  });
  fireEvent.click(within(form).getByRole("button", { name: "保存资料" }));
  await screen.findByRole("alert");
  expect(within(form).getByRole("textbox")).toHaveValue("保留草稿");
  fireEvent.click(within(form).getByRole("button", { name: "取消" }));
  expect(within(row).getByText("合成人物")).toBeInTheDocument();
});

test("ordinary list additions only ask for content while existing object records keep their own fields", () => {
  const field = {
    ...profile.fields[1],
    key: "contributors.records[]",
    label: "讲述者及与人物的关系",
  };
  table({
    ...profile,
    fields: [field],
    entries: [
      entry("contributor-1", field.key, "", {
        value: { name: "合成人物", relationship: "子女" },
      }),
    ],
  });
  fireEvent.click(screen.getByRole("button", { name: "编辑资料" }));
  const form = screen.getByRole("form");
  expect(within(form).getAllByRole("textbox")).toHaveLength(2);
  expect(within(form).getByLabelText("人物名称")).toHaveValue("合成人物");
  expect(within(form).queryByLabelText("发生了什么")).not.toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "取消" }));
  fireEvent.click(screen.getByRole("button", { name: "添加一条" }));
  const added = screen.getByRole("form");
  expect(within(added).getAllByRole("textbox")).toHaveLength(1);
  expect(within(added).getByRole("textbox")).toHaveValue("");
});

test("a concurrent profile update keeps the inline draft and requires acknowledging the new version", async () => {
  const { update } = table();
  const row = screen
    .getByText("书中称呼")
    .closest(".profile-field") as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { name: "编辑资料" }));
  const form = within(row).getByRole("form");
  fireEvent.change(within(form).getByRole("textbox"), {
    target: { value: "新的称呼" },
  });
  update({ ...profile, version_number: 2 });
  expect(within(form).getByRole("textbox")).toHaveValue("新的称呼");
  expect(within(form).getByRole("button", { name: "保存资料" })).toBeDisabled();
  fireEvent.click(
    within(form).getByRole("button", { name: "已核对，按最新版本保存" }),
  );
  fireEvent.click(within(form).getByRole("button", { name: "保存资料" }));
  await waitFor(() => expect(profilesApi.patch).toHaveBeenCalledOnce());
  expect(vi.mocked(profilesApi.patch).mock.calls[0][1]).toBe(2);
});

test("existing records can be removed from their inline editor with version checking", async () => {
  table();
  const row = screen
    .getByText("书中称呼")
    .closest(".profile-field") as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { name: "编辑资料" }));
  fireEvent.click(within(row).getByRole("button", { name: "删除这条资料" }));
  await waitFor(() => expect(profilesApi.patch).toHaveBeenCalledOnce());
  expect(vi.mocked(profilesApi.patch).mock.calls[0][2][0]).toMatchObject({
    id: "name-1",
    delete: true,
  });
});

test("long content expands and collapses without losing its source text", () => {
  table({
    ...profile,
    entries: [entry("name-1", "name", "这是合成的完整往事。".repeat(30))],
  });
  const toggle = screen.getByRole("button", { name: "展开内容" });
  fireEvent.click(toggle);
  expect(screen.getByRole("button", { name: "收起" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  expect(
    screen.getByText("这是合成的完整往事。".repeat(30)),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "收起" }));
  expect(screen.getByRole("button", { name: "展开内容" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});
