import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { WalletPage } from "./WalletPage";
import { ScriptPriceNotice } from "../components/ScriptPriceNotice";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    const data = path.endsWith("/wallet") ? {
      paid_cents: 0, bonus_cents: 2000, frozen_cents: 600, available_cents: 1400,
      prices: { video_cents_per_second: 80, script_chapter_cents: 40, payment_enabled: false },
    } : path.includes("/usage") || path.includes("/recharge/orders") ? { total: 0, items: [] } : {
      total: 1, items: [{ id: "entry", event: "bonus", title: "新用户体验额度", amount_cents: 2000,
        available_after_cents: 2000, created_at: "2026-09-09T00:00:00Z" }],
    };
    return { ok: true, status: 200, json: async () => data } as Response;
  }));
});

test("token mode replaces chapter pricing in wallet and interview notice", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => ({
    ok: true, status: 200, json: async () => String(input).endsWith("/wallet") ? {
      paid_cents: 0, bonus_cents: 2000, frozen_cents: 0, available_cents: 2000,
      token_remainder_nano: 2600000,
      prices: { video_cents_per_second: 80, script_chapter_cents: 40,
        script_billing_mode: "tokens", payment_enabled: false },
    } : { total: 0, items: [] },
  })));
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <WalletPage /><ScriptPriceNotice />
  </MemoryRouter></QueryClientProvider>);
  expect(await screen.findByText("文本 AI 按实际 token 用量计费（官方标准价 × 1.5）")).toBeVisible();
  expect(screen.queryByText("剧本 ¥0.40 / 章 / 次")).not.toBeInTheDocument();
  expect(screen.getByText(/未生成剧本也会产生用量费用/)).toBeVisible();
  expect(screen.getByText(/0.002600/)).toBeVisible();
});

test("shows available balance and disables unconfigured payments", async () => {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><WalletPage /></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByText("¥14.00")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "钱包余额" })).getByText("可用余额")).toBeVisible();
  expect(screen.getByText("剧本 ¥0.40 / 章 / 次")).toBeVisible();
  expect(screen.getByText("影像 ¥0.80 / 秒（¥24.00 / 30 秒）")).toBeVisible();
  expect(screen.getByText("每次成功生成或更新均计费，含采访自动更新、追问、记忆与知识图谱整理及素材理解")).toBeVisible();
  expect(screen.queryByText("同章更新暂不另收费")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "确认支付" })).toBeDisabled();
  expect(await screen.findByText("新用户体验额度")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "¥50.00" }));
  expect(screen.getByRole("button", { name: "¥50.00" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("微信支付")).toBeVisible();
  fireEvent.change(screen.getByLabelText("类型"), { target: { value: "consume" } });
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("event=consume"), expect.anything()));
});
