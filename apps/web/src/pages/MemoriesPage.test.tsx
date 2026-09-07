import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import { MemoriesPage } from "./MemoriesPage";

const people = [
  {
    id: "person-1",
    tenant_id: "tenant-1",
    display_name: "林秀兰",
    preferred_name: "林奶奶",
    birth_year: 1952,
    birthplace: "福建泉州",
    relation_to_owner: "外婆",
    is_subject: true,
    biography_note: null,
    is_minor: false,
    guardian_name: null,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  },
  {
    id: "person-2",
    tenant_id: "tenant-1",
    display_name: "周明远",
    preferred_name: null,
    birth_year: 1948,
    birthplace: "浙江宁波",
    relation_to_owner: "爷爷",
    is_subject: true,
    biography_note: "年轻时在船厂工作。",
    is_minor: false,
    guardian_name: null,
    created_at: "2026-09-02T00:00:00Z",
    updated_at: "2026-09-02T00:00:00Z",
  },
];

function response(payload: unknown) {
  return { ok: true, status: 200, json: async () => payload } as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/v1/persons")) return response(people);
    const personId = url.includes("person-2") ? "person-2" : "person-1";
    if (url.includes("/graph")) return response({
      subject_id: personId,
      nodes: personId === "person-1" ? [
        { id: "subject:person-1", kind: "subject", label: "林奶奶", description: "我在泉州长大。", time_text: null, source_claim_ids: [] },
        { id: "entity:sister", kind: "person", label: "姐姐", description: "常和姐姐去村口。", time_text: null, source_claim_ids: ["claim-1"] },
        { id: "event:childhood", kind: "event", label: "和姐姐去村口", description: "小时候常和姐姐去村口。", time_text: "小时候", source_claim_ids: ["claim-1"] },
      ] : [
        { id: "subject:person-2", kind: "subject", label: "周明远", description: "年轻时在船厂工作。", time_text: null, source_claim_ids: [] },
      ],
      edges: personId === "person-1" ? [
        { id: "edge-1", source_id: "subject:person-1", target_id: "entity:sister", relationship: "姐姐", source_claim_ids: ["claim-1"] },
        { id: "edge-2", source_id: "subject:person-1", target_id: "event:childhood", relationship: "经历", source_claim_ids: ["claim-1"] },
      ] : [],
    });
    if (url.includes("/overview")) return response({ claim_count: personId === "person-1" ? 1 : 0, reviewed_count: 0, entity_count: 1, timeline_count: personId === "person-1" ? 1 : 0, open_conflict_count: 0, covered_chapter_ids: [], coverage_ratio: 0.2 });
    if (url.includes("/timeline")) return response(personId === "person-1" ? [{ id: "timeline-1", subject_id: personId, claim_id: "claim-1", year: null, time_text: "小时候", event_text: "小时候常和姐姐去村口。", precision: "relative" }] : []);
    if (url.includes("/conflicts")) return response([]);
    if (url.includes("/v1/memories?")) return response(personId === "person-1" ? [{ id: "claim-1", claim_text: "小时候常和姐姐去村口。", source_quote: "小时候，我常和姐姐去村口。", source_claim_ids: [] }] : []);
    if (url.includes("/v1/evidence/assets")) return response([{
      id: personId === "person-1" ? "asset-lin" : "asset-zhou",
      subject_id: personId,
      interview_session_id: "session-1",
      kind: "photo",
      original_filename: personId === "person-1" ? "泉州老照片.jpg" : "船厂合影.jpg",
      mime_type: "image/jpeg",
      byte_size: 2048,
      sha256: "hash",
      status: "ready",
      consent_scope: "private",
      captured_at: "2026-09-01T00:00:00Z",
      created_at: "2026-09-01T00:00:00Z",
    }]);
    return response([]);
  }) as unknown as typeof fetch);
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><MemoriesPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders a traceable read-only memory graph and file archive", async () => {
  renderPage();
  expect(await screen.findByRole("heading", { name: "人物关系图谱" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /林奶奶的记忆关系图/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^姐姐 姐姐 1 条来源$/ }));
  expect(screen.getByText("小时候，我常和姐姐去村口。")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "泉州老照片.jpg" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /上传|编译|确认真实|标记存疑/ })).not.toBeInTheDocument();
});

test("switching people isolates graph and files", async () => {
  renderPage();
  const picker = await screen.findByRole("combobox", { name: "当前人物" });
  expect((await screen.findAllByText("泉州老照片.jpg")).length).toBeGreaterThan(0);
  fireEvent.change(picker, { target: { value: "person-2" } });
  expect(await screen.findByRole("heading", { name: "周明远" })).toBeInTheDocument();
  expect((await screen.findAllByText("船厂合影.jpg")).length).toBeGreaterThan(0);
  expect(screen.queryByText("泉州老照片.jpg")).not.toBeInTheDocument();
  await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
    "/v1/evidence/assets?subject_id=person-2",
    expect.anything(),
  ));
});
