import type { RechargeOrder, WalletSummary } from "@lifereel/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CreditCard, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, API_BASE_URL } from "../api/client";
import { ErrorNotice, QueryState } from "./QueryState";
import { RechargeDialog } from "./RechargeDialog";

const money = (cents: number) => `¥${(cents / 100).toFixed(2)}`;

export function parseRechargeAmount(value: string): number | null {
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return null;
  const [yuan, fraction = ""] = value.split(".");
  const cents = Number(yuan) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(cents) && cents >= 1 && cents <= 20000
    ? cents
    : null;
}

export function WalletRecharge({ wallet }: { wallet: WalletSummary }) {
  const client = useQueryClient();
  const enabled = wallet.recharge?.mode === "manual_wechat";
  const [amount, setAmount] = useState(10);
  const [customAmount, setCustomAmount] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<RechargeOrder | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [imageAttempt, setImageAttempt] = useState(0);
  const [modalOpen, setModalOpen] = useState(false);
  const [success, setSuccess] = useState("");
  const request = useRef<{ amount: number; id: string } | null>(null);
  const orders = useQuery({
    queryKey: ["recharge-orders", page],
    queryFn: () => api.rechargeOrders(page),
    refetchInterval: 10000,
  });
  const detail = useQuery({
    queryKey: ["recharge-order", selected?.id],
    queryFn: () => api.rechargeOrder(selected!.id),
    enabled: !!selected,
    refetchInterval: (query) =>
      ["credited", "rejected", "cancelled"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 3000,
  });
  const order = detail.data ?? selected;
  const cents =
    amount === -1 ? parseRechargeAmount(customAmount) : amount * 100;
  const paidOrders =
    orders.data?.items.filter((row) => row.status === "credited") ?? [];
  const paidRevision = paidOrders.map((row) => row.id).join(",");
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["recharge-orders"] }),
      client.invalidateQueries({ queryKey: ["wallet"] }),
      client.invalidateQueries({ queryKey: ["wallet-ledger"] }),
    ]);

  useEffect(() => {
    if (paidRevision) {
      void client.invalidateQueries({ queryKey: ["wallet"] });
      void client.invalidateQueries({ queryKey: ["wallet-ledger"] });
    }
  }, [client, paidRevision]);
  useEffect(() => {
    if (order?.status === "credited") {
      void client.invalidateQueries({ queryKey: ["wallet"] });
      void client.invalidateQueries({ queryKey: ["wallet-ledger"] });
      void client.invalidateQueries({ queryKey: ["recharge-orders"] });
      setSuccess(`充值成功，${money(order.amount_cents)} 已入账。`);
      setModalOpen(false);
      setSelected(null);
    }
  }, [client, order?.id, order?.status, order?.amount_cents]);

  const create = useMutation({
    mutationFn: api.createRecharge,
    onSuccess: (row) => {
      request.current = null;
      setSelected(row);
      client.setQueryData(["recharge-order", row.id], row);
    },
  });

  function openPayment() {
    if (cents === null || create.isPending || !enabled) return;
    setSuccess("");
    setImageFailed(false);
    setModalOpen(true);
    if (order?.status === "pending" && order.amount_cents === cents) {
      void detail.refetch();
      return;
    }
    setSelected(null);
    if (request.current?.amount !== cents)
      request.current = { amount: cents, id: crypto.randomUUID() };
    create.mutate({ request_id: request.current.id, amount_cents: cents });
  }

  return (
    <>
      <section className="wallet-recharge" aria-labelledby="recharge-title">
        <div>
          <h2 id="recharge-title">在线充值</h2>
          <p className="wallet-note">
            {enabled
              ? "个人收款码测试 · 人工核实后入账，单笔 0.01–200 元。"
              : "充值暂未开通，请勿付款。"}
          </p>
        </div>
        <fieldset disabled={create.isPending}>
          <legend>支付金额</legend>
          <div className="wallet-amounts">
            {[10, 50, 100, 200].map((value) => (
              <button
                type="button"
                key={value}
                aria-pressed={amount === value}
                className={amount === value ? "selected" : ""}
                onClick={() => setAmount(value)}
              >
                {money(value * 100)}
              </button>
            ))}
            <button
              type="button"
              aria-pressed={amount === -1}
              className={amount === -1 ? "selected" : ""}
              onClick={() => setAmount(-1)}
            >
              其它金额
            </button>
          </div>
          {amount === -1 && (
            <>
              <input
                className="wallet-custom-amount"
                inputMode="decimal"
                value={customAmount}
                onChange={(e) => setCustomAmount(e.target.value)}
                placeholder="0.01–200 元"
                aria-label="自定义充值金额"
                aria-invalid={cents === null}
                aria-describedby="recharge-amount-hint"
              />
              <p id="recharge-amount-hint" className="wallet-note">
                金额为 0.01–200 元，最多两位小数；首次可用 0.01 元测试。
              </p>
            </>
          )}
        </fieldset>
        <fieldset>
          <legend>支付方式</legend>
          <div className="wallet-pay-methods">
            <div className="selected">微信支付</div>
          </div>
        </fieldset>
        <div className="wallet-actions">
          <button
            className="button primary"
            disabled={!enabled || cents === null || create.isPending}
            onClick={openPayment}
          >
            <CreditCard size={17} />
            {create.isPending ? "正在准备支付" : "确认支付"}
          </button>
        </div>
        {success && (
          <p className="recharge-success" role="status">
            {success}
          </p>
        )}
      </section>

      {modalOpen && (
        <RechargeDialog onClose={() => setModalOpen(false)}>
          {create.isPending && (
            <p className="recharge-progress" role="status">
              正在准备支付…
            </p>
          )}
          {create.isError && !order && (
            <div className="recharge-dialog-error">
              <ErrorNotice error={create.error} />
              <button
                className="button primary"
                onClick={openPayment}
                disabled={create.isPending}
              >
                重新加载
              </button>
            </div>
          )}
          {order && (
            <div className="recharge-checkout">
              {order.status === "pending" && enabled && (
                <>
                  <div className="recharge-qr">
                    <img
                      src={`${API_BASE_URL}/v1/wallet/recharge/qr?attempt=${imageAttempt}`}
                      alt="微信收款码"
                      onLoad={() => setImageFailed(false)}
                      onError={() => setImageFailed(true)}
                    />
                  </div>
                  <p className="recharge-payment-hint">
                    请使用微信扫码支付 {money(order.amount_cents)}
                    ，收款核实后到账。
                  </p>
                </>
              )}
              {order.status === "pending" && !enabled && (
                <p role="alert" className="form-error">
                  支付暂不可用，请勿付款。
                </p>
              )}
              {order.status === "submitted" && (
                <p className="recharge-payment-hint">
                  收款核实中，请勿重复付款。
                </p>
              )}
              {order.status === "rejected" && (
                <p role="alert" className="form-error">
                  充值核实未通过，余额未增加。
                  {order.review_note || "请联系收款方核对，请勿重复付款。"}
                </p>
              )}
              {order.status === "cancelled" && (
                <p role="alert" className="form-error">
                  本次支付已关闭，请重新发起充值。
                </p>
              )}
              {imageFailed && (
                <div className="recharge-dialog-error" role="alert">
                  收款码加载失败，请重试。
                  <button
                    className="button secondary small"
                    onClick={() => {
                      setImageFailed(false);
                      setImageAttempt((value) => value + 1);
                    }}
                  >
                    重新加载二维码
                  </button>
                </div>
              )}
              {detail.isError && (
                <div className="recharge-dialog-error" role="alert">
                  暂时无法获取支付状态，不代表付款失败，请勿重复付款。
                  <button
                    className="button secondary small"
                    disabled={detail.isFetching}
                    onClick={() => void detail.refetch()}
                  >
                    重试查询
                  </button>
                </div>
              )}
            </div>
          )}
        </RechargeDialog>
      )}

      <section className="recharge-history" aria-label="充值记录">
        <div className="wallet-history-bar">
          <h2>充值记录</h2>
          <button
            className="icon-button"
            title="刷新充值记录"
            aria-label="刷新充值记录"
            disabled={orders.isFetching}
            onClick={() => void refresh()}
          >
            <RefreshCw size={17} />
          </button>
        </div>
        <QueryState queries={[orders]} />
        <div className="recharge-order-list">
          {paidOrders.map((row) => (
            <div className="recharge-receipt" key={row.id}>
              <span>
                <strong>{money(row.amount_cents)}</strong>
                <small>
                  {new Date(row.reviewed_at ?? row.created_at).toLocaleString(
                    "zh-CN",
                  )}
                </small>
              </span>
              <span>充值成功</span>
            </div>
          ))}
        </div>
        {orders.isSuccess && !paidOrders.length && (
          <p className="wallet-note">暂无充值记录</p>
        )}
        {!!orders.data?.total && (
          <nav className="wallet-pagination" aria-label="充值记录翻页">
            <span>第 {page} 页</span>
            <button
              className="icon-button"
              title="上一页充值记录"
              aria-label="上一页充值记录"
              disabled={page <= 1 || orders.isFetching}
              onClick={() => setPage(page - 1)}
            >
              <ArrowLeft size={17} />
            </button>
            <button
              className="icon-button"
              title="下一页充值记录"
              aria-label="下一页充值记录"
              disabled={orders.isFetching || page * 20 >= orders.data.total}
              onClick={() => setPage(page + 1)}
            >
              <ArrowRight size={17} />
            </button>
          </nav>
        )}
      </section>
    </>
  );
}
