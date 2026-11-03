import type { Person } from "@lifereel/contracts";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import { ApiError } from "../api/errors";
import { PeoplePage } from "./PeoplePage";

const person = {
  id: "person-one",
  display_name: "林奶奶",
  is_minor: false,
} as Person;

afterEach(() => vi.restoreAllMocks());

function setup() {
  vi.spyOn(api, "listPersons").mockResolvedValue([person]);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <PeoplePage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
  return client;
}

test("delete requires confirmation and can return to editing without a request", async () => {
  const remove = vi.spyOn(api, "deletePerson").mockResolvedValue();
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "编辑林奶奶" }));
  fireEvent.click(screen.getByRole("button", { name: "删除家人" }));
  expect(screen.getByText(/采访记录/)).toBeInTheDocument();
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "返回编辑" }));
  expect(screen.getByRole("button", { name: "保存人物" })).toBeInTheDocument();
  expect(remove).not.toHaveBeenCalled();
});

test("confirmed deletion removes the person and invalidates dependent cached data", async () => {
  const remove = vi.spyOn(api, "deletePerson").mockImplementation(async () => {
    vi.mocked(api.listPersons).mockResolvedValue([]);
  });
  const client = setup();
  client.setQueryData(["books"], [{ id: "old-book" }]);
  fireEvent.click(await screen.findByRole("button", { name: "编辑林奶奶" }));
  fireEvent.click(screen.getByRole("button", { name: "删除家人" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除家人" }));
  await screen.findByRole("status");
  expect(remove).toHaveBeenCalledOnce();
  expect(remove.mock.calls[0][0]).toBe(person.id);
  expect(
    screen.queryByRole("button", { name: "编辑林奶奶" }),
  ).not.toBeInTheDocument();
  expect(client.getQueryState(["books"])?.isInvalidated).toBe(true);
});

test("failed deletion preserves the dialog and allows retry", async () => {
  const remove = vi
    .spyOn(api, "deletePerson")
    .mockRejectedValue(new ApiError("PERSON_DELETE_BUSY", 409));
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "编辑林奶奶" }));
  fireEvent.click(screen.getByRole("button", { name: "删除家人" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除家人" }));
  await screen.findByText(/账号中还有采访、生成或计费任务/);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "确认删除家人" })).toBeEnabled(),
  );
  expect(remove).toHaveBeenCalledOnce();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

test("new person form has no delete action", () => {
  setup();
  fireEvent.click(screen.getByRole("button", { name: "添加家人" }));
  expect(
    screen.queryByRole("button", { name: "删除家人" }),
  ).not.toBeInTheDocument();
});
