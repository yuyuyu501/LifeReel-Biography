import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";

function renderShell(route = "/") {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[route]}>
        <AppShell>
          <p>页面内容</p>
        </AppShell>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("separates numbered workflow steps from personal information", () => {
  renderShell();
  const workflow = screen.getByRole("navigation", { name: "生命档案流程" });
  const profile = screen.getByRole("navigation", {
    name: "个人资料",
  });
  expect(
    within(workflow)
      .getAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual(["家人01", "采访02", "剧本03", "影像04"]);
  expect(
    within(profile)
      .getAllByRole("link")
      .map((link) => link.textContent),
  ).toEqual(["记忆", "钱包"]);
  expect(
    screen.queryByRole("link", { name: "首页" }),
  ).not.toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "岁忆影传首页" })).toHaveLength(2);
});

test("highlights a workflow step on a subpage and returns home through the brand", () => {
  renderShell("/interviews/example");
  const workflow = within(
    screen.getByRole("navigation", { name: "生命档案流程" }),
  );
  expect(workflow.getByRole("link", { name: "采访" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  fireEvent.click(screen.getAllByRole("link", { name: "岁忆影传首页" })[0]);
  expect(workflow.getByRole("link", { name: "采访" })).not.toHaveAttribute(
    "aria-current",
  );
  expect(screen.getByText("首页", { exact: true })).toBeInTheDocument();
});

test("keeps both personal destinations accessible through mobile shortcuts", () => {
  renderShell("/wallet");
  const shortcuts = within(
    screen.getByRole("navigation", { name: "个人资料快捷入口" }),
  );
  expect(shortcuts.getByRole("link", { name: "钱包" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  fireEvent.click(shortcuts.getByRole("link", { name: "记忆" }));
  expect(shortcuts.getByRole("link", { name: "记忆" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(
    within(
      screen.getByRole("navigation", { name: "个人资料" }),
    ).getByRole("link", { name: "记忆" }),
  ).toHaveAttribute("aria-current", "page");
});
