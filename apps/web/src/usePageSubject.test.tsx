import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { usePageSubject } from "./usePageSubject";

const people = [{ id: "chen", is_subject: true }, { id: "lin", is_subject: true }];
function setup(user = "owner", tenant = "family") {
  const client = new QueryClient();
  client.setQueryData(["auth-me"], { id: user, tenant_id: tenant });
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}
beforeEach(() => { localStorage.clear(); });

test("restores a page selection after a fresh mount and query client", () => {
  const first = renderHook(() => usePageSubject("interviews", people), { wrapper: setup() });
  act(() => first.result.current[1]("lin"));
  first.unmount();
  const restored = renderHook(() => usePageSubject("interviews", people), { wrapper: setup() });
  expect(restored.result.current[0]).toBe("lin");
});

test("keeps page, account and family selections independent", () => {
  const first = renderHook(() => usePageSubject("interviews", people), { wrapper: setup() });
  act(() => first.result.current[1]("lin"));
  for (const [page, user, tenant] of [
    ["memories", "owner", "family"], ["studio", "owner", "family"],
    ["interviews", "another", "family"], ["interviews", "owner", "another"],
  ] as const) {
    const other = renderHook(() => usePageSubject(page, people), { wrapper: setup(user, tenant) });
    expect(other.result.current[0]).toBe("chen");
    other.unmount();
  }
});

test("waits for people before restoring and validates deleted or non-subject IDs", () => {
  const key = "lifereel:page-subject:family:owner:interviews";
  localStorage.setItem(key, "lin");
  const hook = renderHook(({ data }) => usePageSubject("interviews", data), {
    wrapper: setup(), initialProps: { data: undefined as typeof people | undefined },
  });
  expect(localStorage.getItem(key)).toBe("lin");
  hook.rerender({ data: people });
  expect(hook.result.current[0]).toBe("lin");
  hook.rerender({ data: [{ id: "lin", is_subject: false }, people[0]] });
  expect(hook.result.current[0]).toBe("chen");
  expect(localStorage.getItem(key)).toBe("chen");
  hook.rerender({ data: [] });
  expect(hook.result.current[0]).toBe("");
  expect(localStorage.getItem(key)).toBeNull();
});

test("explicit project links override cached studio selection, then allow switching", () => {
  localStorage.setItem("lifereel:page-subject:family:owner:studio", "chen");
  const hook = renderHook(() => usePageSubject("studio", people, "lin"), { wrapper: setup() });
  expect(hook.result.current[0]).toBe("lin");
  act(() => hook.result.current[1]("chen"));
  expect(hook.result.current[0]).toBe("chen");
});

test("blocked browser storage does not prevent selecting a person", () => {
  const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  const write = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  try {
    const hook = renderHook(() => usePageSubject("interviews", people), { wrapper: setup() });
    act(() => hook.result.current[1]("lin"));
    expect(hook.result.current[0]).toBe("lin");
  } finally { read.mockRestore(); write.mockRestore(); }
});
