import type { RechargeOrder, WalletSummary } from "@lifereel/contracts";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api } from "../api/client";
import { parseRechargeAmount, WalletRecharge } from "./WalletRecharge";

const wallet: WalletSummary = {
  paid_cents: 0,
  bonus_cents: 2000,
  frozen_cents: 0,
  available_cents: 2000,
  recharge: { mode: "manual_wechat", min_cents: 1, max_cents: 20000 },
  prices: {
    version: "test",
    video_cents_per_second: 80,
    script_chapter_cents: 40,
    welcome_bonus_cents: 2000,
    payment_enabled: false,
    script_billing_mode: "per_update",
  },
};
let rows: RechargeOrder[];
const pending = (): RechargeOrder => ({
  id: "10000000-0000-4000-8000-000000000001",
  amount_cents: 1,
  status: "pending",
  payer_reference: null,
  review_note: null,
  created_at: "2026-09-09T00:00:00Z",
  reviewed_at: null,
});

beforeEach(() => {
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: {
      configurable: true,
      value() {
        this.setAttribute("open", "");
      },
    },
    close: {
      configurable: true,
      value() {
        this.removeAttribute("open");
      },
    },
  });
  rows = [];
  vi.spyOn(api, "wallet").mockImplementation(async () => ({
    ...wallet,
    available_cents:
      2000 +
      rows
        .filter((r) => r.status === "credited")
        .reduce((sum, r) => sum + r.amount_cents, 0),
  }));
  vi.spyOn(api, "rechargeOrders").mockImplementation(async () => ({
    total: rows.filter((row) => row.status === "credited").length,
    items: rows.filter((row) => row.status === "credited"),
    page: 1,
    page_size: 20,
  }));
  vi.spyOn(api, "rechargeOrder").mockImplementation(async (id) =>
    rows.find((r) => r.id === id)!,
  );
  vi.spyOn(api, "createRecharge").mockImplementation(
    async ({ amount_cents }) => {
      const row = { ...pending(), amount_cents };
      rows = [row];
      return row;
    },
  );
  vi.spyOn(api, "reportRecharge").mockImplementation(
    async (id, payer_reference) => {
      rows = rows.map((r) =>
        r.id === id ? { ...r, status: "submitted", payer_reference } : r,
      );
      return rows[0];
    },
  );
  vi.spyOn(api, "cancelRecharge").mockImplementation(async () => {
    rows = [{ ...rows[0], status: "cancelled" }];
    return rows[0];
  });
});
afterEach(() => vi.restoreAllMocks());

function BalanceObserver() {
  const { data } = useQuery({ queryKey: ["wallet"], queryFn: api.wallet });
  return <span data-testid="available-balance">{data?.available_cents}</span>;
}

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <BalanceObserver />
      <WalletRecharge wallet={wallet} />
    </QueryClientProvider>,
  );
  return client;
}

test.each([
  ["0.01", 1],
  ["0.29", 29],
  ["200", 20000],
  ["200.00", 20000],
  ["0", null],
  ["-1", null],
  ["200.01", null],
  ["0.001", null],
  ["1e2", null],
  ["Infinity", null],
  ["", null],
  ["1.1", 110],
])("parses yuan %s exactly as %s cents", (value, cents) => {
  expect(parseRechargeAmount(value as string)).toBe(cents);
});

test("shows only the QR, one hint and close control without crediting", async () => {
  mount();
  fireEvent.click(screen.getByRole("button", { name: "其它金额" }));
  const submit = screen.getByRole("button", { name: "确认支付" });
  expect(submit).toBeDisabled();
  fireEvent.change(screen.getByLabelText("自定义充值金额"), {
    target: { value: "0.01" },
  });
  fireEvent.click(submit);
  const dialog = await screen.findByRole("dialog", { name: "微信扫码支付" });
  expect(dialog).toBeVisible();
  expect(
    await screen.findByRole("img", { name: /微信收款码/ }),
  ).toHaveAttribute("src", expect.stringContaining("/v1/wallet/recharge/qr"));
  expect(api.createRecharge).toHaveBeenCalledWith(
    expect.objectContaining({ amount_cents: 1 }),
    expect.anything(),
  );
  expect(within(dialog).getAllByRole("button")).toHaveLength(1);
  expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();
  expect(dialog).not.toHaveTextContent(pending().id);
  expect(dialog).toHaveTextContent(
    "请使用微信扫码支付 ¥0.01，收款核实后到账。",
  );
  expect(screen.getByTestId("available-balance")).toHaveTextContent("2000");
  expect(api.reportRecharge).not.toHaveBeenCalled();
});

test("network retries reuse the order key and closing leaves no visible record", async () => {
  vi.mocked(api.createRecharge).mockRejectedValueOnce(
    new Error("Network error"),
  );
  mount();
  const button = screen.getByRole("button", { name: "确认支付" });
  fireEvent.click(button);
  await waitFor(() => expect(api.createRecharge).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
  await screen.findByRole("img", { name: /微信收款码/ });
  expect(vi.mocked(api.createRecharge).mock.calls[0][0]).toEqual(
    vi.mocked(api.createRecharge).mock.calls[1][0],
  );
  fireEvent.click(screen.getByRole("button", { name: "关闭支付窗口" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(await screen.findByText("暂无充值记录")).toBeVisible();
  expect(api.cancelRecharge).not.toHaveBeenCalled();
});

test("history only renders credited payments without internal order numbers", async () => {
  rows = ["pending", "submitted", "cancelled", "rejected", "credited"].map(
    (status, index) => ({
      ...pending(),
      id: `hidden-order-${index}`,
      amount_cents: 121 + index,
      status: status as RechargeOrder["status"],
    }),
  );
  vi.mocked(api.rechargeOrders).mockResolvedValue({
    total: 1,
    items: rows,
    page: 1,
    page_size: 20,
  });
  mount();
  const history = within(screen.getByRole("region", { name: "充值记录" }));
  expect(await history.findByText("¥1.25")).toBeVisible();
  for (const text of [
    "¥1.21",
    "¥1.22",
    "¥1.23",
    "¥1.24",
    "待付款",
    "待核实",
    "已取消",
    "核实未通过",
  ]) {
    expect(history.queryByText(text)).not.toBeInTheDocument();
  }
  expect(screen.queryByText(/hidden-order/)).not.toBeInTheDocument();
  expect(api.createRecharge).not.toHaveBeenCalled();
});

test("verified credit refreshes the balance and closes the payment dialog", async () => {
  const client = mount();
  fireEvent.click(screen.getByRole("button", { name: "确认支付" }));
  await screen.findByRole("img", { name: /微信收款码/ });
  expect(screen.getByTestId("available-balance")).toHaveTextContent("2000");
  await act(async () => {
    rows = [{ ...rows[0], status: "credited" }];
    await client.invalidateQueries({ queryKey: ["recharge-order"] });
  });
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
  );
  expect(await screen.findByText("充值成功，¥10.00 已入账。")).toBeVisible();
  await waitFor(() =>
    expect(screen.getByTestId("available-balance")).toHaveTextContent("3000"),
  );
});

test("closing or escaping preserves the order, restores focus and allows reopening", async () => {
  mount();
  const trigger = screen.getByRole("button", { name: "确认支付" });
  trigger.focus();
  fireEvent.click(trigger);
  await screen.findByRole("img", { name: /微信收款码/ });
  await waitFor(() => expect(trigger).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "关闭支付窗口" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(document.body.style.overflow).not.toBe("hidden");
  expect(api.cancelRecharge).not.toHaveBeenCalled();
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog");
  expect(api.createRecharge).toHaveBeenCalledTimes(1);
  fireEvent.keyDown(dialog, { key: "Escape", code: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("rejection stays visible and never credits the wallet", async () => {
  const client = mount();
  fireEvent.click(screen.getByRole("button", { name: "确认支付" }));
  await screen.findByRole("img", { name: /微信收款码/ });
  await act(async () => {
    rows = [{ ...rows[0], status: "rejected", review_note: "金额不符" }];
    await client.invalidateQueries({ queryKey: ["recharge-order"] });
  });
  expect(
    await within(screen.getByRole("dialog")).findByRole("alert"),
  ).toHaveTextContent("金额不符");
  expect(screen.getByTestId("available-balance")).toHaveTextContent("2000");
});

test("QR and status network failures offer retries without declaring payment failure", async () => {
  const client = mount();
  fireEvent.click(screen.getByRole("button", { name: "确认支付" }));
  const qr = await screen.findByRole("img", { name: /微信收款码/ });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "确认支付", hidden: true }),
    ).toBeEnabled(),
  );
  fireEvent.error(qr);
  expect(screen.getByRole("alert")).toHaveTextContent("收款码加载失败");
  fireEvent.click(screen.getByRole("button", { name: "重新加载二维码" }));
  expect(qr).toHaveAttribute("src", expect.stringContaining("attempt=1"));
  vi.mocked(api.rechargeOrder).mockRejectedValueOnce(
    new Error("Network error"),
  );
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["recharge-order"] });
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("不代表付款失败");
  fireEvent.click(screen.getByRole("button", { name: "重试查询" }));
  await waitFor(() =>
    expect(screen.queryByText(/暂时无法获取支付状态/)).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("dialog")).toBeVisible();
});
