import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { QueryState } from "./QueryState";

it("retries every failed query together and disables repeat clicks while fetching", () => {
  const first = vi.fn().mockResolvedValue({});
  const second = vi.fn().mockResolvedValue({});
  const queries = [
    {
      isPending: false,
      isError: true,
      isFetching: false,
      error: new Error("first failed"),
      refetch: first,
    },
    {
      isPending: false,
      isError: true,
      isFetching: false,
      error: new Error("second failed"),
      refetch: second,
    },
  ];
  const view = render(<QueryState queries={queries} />);
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(first).toHaveBeenCalledOnce();
  expect(second).toHaveBeenCalledOnce();
  view.rerender(
    <QueryState
      queries={queries.map((query) => ({ ...query, isFetching: true }))}
    />,
  );
  expect(screen.getByRole("button", { name: "正在重试" })).toBeDisabled();
});
