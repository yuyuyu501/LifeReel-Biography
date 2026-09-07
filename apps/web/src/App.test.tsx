import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, vi } from "vitest";
import App from "./App";

function response(ok: boolean, status: number, payload: unknown) {
  return { ok, status, json: async () => payload } as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/v1/auth/me")) return response(true, 200, { display_name: "测试用户", role: "owner" });
    return response(true, 200, []);
  }) as unknown as typeof fetch);
});

test("renders the LifeReel home experience", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "继续整理这份人生" })).toBeInTheDocument();
  expect(await screen.findByText("从讲述到成片")).toBeInTheDocument();
});

test("redirects an expired session to the Chinese login page", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => response(false, 401, { error: { code: "AUTH_REQUIRED" } })) as unknown as typeof fetch);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "登录后继续整理" })).toBeInTheDocument();
});

test("redirects the old material page to the memory archive", async () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/evidence"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "记忆档案" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /^素材/ })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: /记忆档案/ })).toHaveAttribute("href", "/memories");
});
