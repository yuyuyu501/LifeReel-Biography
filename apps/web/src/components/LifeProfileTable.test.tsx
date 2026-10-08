import type { LifeProfile, ProfileEntry } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { LifeProfileTable } from "./LifeProfileTable";

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
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })),
  );
});
function table(data = profile) {
  const onTalk = vi.fn();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <LifeProfileTable profile={data} onTalk={onTalk} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onTalk;
}

test("missing filters exclude declined answers and confirmation filters exclude confirmed entries", () => {
  table();
  fireEvent.click(screen.getByRole("button", { name: /^待补充/ }));
  expect(screen.getByText("出生时间")).toBeInTheDocument();
  expect(screen.queryByText("家庭")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^待确认/ }));
  expect(screen.getByText("时间记不清，需要核实")).toBeInTheDocument();
  expect(screen.queryByText("已确认的第二段经历")).not.toBeInTheDocument();
  expect(screen.getByText("待澄清")).toBeInTheDocument();
  expect(screen.getByText("内部资料")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("资料分类"), {
    target: { value: "A" },
  });
  expect(screen.getByText("此分类没有待确认的资料")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^全部/ }));
  expect(screen.getByText("合成人物")).toBeInTheDocument();
});

test("metadata can be expanded without hiding privacy flags or mutating the record", () => {
  table();
  expect(screen.queryByText("大约是那年夏天")).not.toBeInTheDocument();
  const info = screen.getAllByRole("button", {
    name: "查看工作经历的来源与权限",
    hidden: true,
  })[0];
  fireEvent.click(info);
  expect(info).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("大约是那年夏天")).toBeInTheDocument();
  expect(screen.getByText("只用于内部资料")).toBeInTheDocument();
  fireEvent.click(info);
  expect(screen.queryByText("大约是那年夏天")).not.toBeInTheDocument();
});

test("filtered fields still support interviewing and editing, with filters locked while editing", () => {
  const onTalk = table();
  fireEvent.click(screen.getByRole("button", { name: /^待补充/ }));
  fireEvent.click(screen.getByRole("button", { name: "在聊天中补充" }));
  expect(onTalk).toHaveBeenCalledWith(profile.fields[1]);
  fireEvent.click(screen.getByRole("button", { name: "填写" }));
  const form = screen.getByRole("form", { name: "编辑出生时间" });
  expect(screen.getByLabelText("资料分类")).toBeDisabled();
  expect(screen.getByRole("button", { name: /^全部/ })).toBeDisabled();
  fireEvent.click(within(form).getByRole("button", { name: "取消" }));
  expect(screen.getByLabelText("资料分类")).toBeEnabled();
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
