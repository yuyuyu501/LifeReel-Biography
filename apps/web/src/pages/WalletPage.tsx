import { Button } from "../components/ui/button";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { api } from "../api/client";
import { QueryState } from "../components/QueryState";
import { WalletRecharge } from "../components/WalletRecharge";

export const money = (cents: number) => `¥${(cents / 100).toFixed(2)}`;
const events: Record<string, string> = {
  recharge: "充值",
  bonus: "赠送",
  reserve: "冻结",
  consume: "消费",
  release: "解冻",
};

export function WalletPage() {
  const [event, setEvent] = useState("");
  const [page, setPage] = useState(1);
  const wallet = useQuery({
    queryKey: ["wallet"],
    queryFn: api.wallet,
    refetchInterval: 10000,
  });
  const ledger = useQuery({
    queryKey: ["wallet-ledger", page, event],
    queryFn: () => api.walletLedger(page, event),
  });
  const w = wallet.data;
  return (
    <div className="page wallet-page">
      <header className="page-title-row">
        <div>
          <span className="eyebrow">家庭账户</span>
          <h1>钱包</h1>
        </div>
      </header>
      <QueryState queries={[wallet]} />
      {w && (
        <>
          <section className="wallet-summary" aria-label="钱包余额">
            <div className="wallet-available">
              <span>可用余额</span>
              <strong>{money(w.available_cents)}</strong>
              {(w.debt_cents ?? 0) > 0 && (
                <small role="status">
                  当前欠款 {money(w.debt_cents!)}，充值后抵扣
                </small>
              )}
              {w.prices.script_billing_mode === "tokens" && (
                <small>
                  预冻结 {money(w.frozen_cents)} · 待累计结算 ¥
                  {((w.token_remainder_nano ?? 0) / 1e9).toFixed(6)}
                </small>
              )}
            </div>
          </section>
          <WalletRecharge wallet={w} />
          <div className="wallet-rates">
            <span>当前价格</span>
            {w.prices.video_billing_mode === "tokens" ? (
              <>
                <span>
                  影像按实际 token 用量计费（官方标准价 ×{" "}
                  {w.prices.video_markup ?? "1.5"}）
                </span>
                <span>
                  720p 每百万计费 token：无视频参考 ¥
                  {w.prices.video_cny_per_million ?? "34.5"}，有视频参考 ¥
                  {w.prices.video_reference_cny_per_million ?? "21"}
                  。分镜规划按文本 AI 单价计费。
                </span>
                <span>
                  每次预冻结 {money(w.prices.video_reserve_cents ?? 2400)}
                  ，按实际用量多退少补；欠款结清后可再次生成。
                </span>
              </>
            ) : (
              <span>
                影像 {money(w.prices.video_cents_per_second)} / 秒（
                {money(w.prices.video_cents_per_second * 30)} / 30 秒）
              </span>
            )}
            {w.prices.script_billing_mode === "tokens" ? (
              <>
                <span>文本 AI 按实际 token 用量计费（官方标准价 × 1.5）</span>
                <span>
                  每百万 token：输入 ≤32K 时输入 ¥1.20 / 输出 ¥3.00；32K–128K
                  时输入 ¥1.80 / 输出 ¥9.00；缓存命中输入 ¥0.24。
                </span>
                <span>
                  含采访追问、记忆整理和剧本生成，不再按章收费。每次调用预冻结
                  ¥0.40，按实际用量结算；不足一分钱累计，有消耗但未成稿仍计费，未知用量待核对。
                </span>
              </>
            ) : (
              <>
                <span>
                  剧本 {money(w.prices.script_chapter_cents)} / 章 / 次
                </span>
                <span>
                  每次成功生成或更新均计费，含采访自动更新、追问、记忆与知识图谱整理及素材理解
                </span>
              </>
            )}
          </div>
        </>
      )}
      <section className="wallet-history" aria-label="钱包明细">
        <div className="wallet-history-bar">
          <strong>消费明细</strong>
          <label>
            类型
            <select
              value={event}
              onChange={(e) => {
                setEvent(e.target.value);
                setPage(1);
              }}
            >
              <option value="">全部</option>
              {Object.entries(events).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <QueryState queries={[ledger]} />
        {ledger.isSuccess && (
          <div className="wallet-table-scroll">
            <table className="wallet-table">
              <thead>
                <tr>
                  {["时间", "事项", "类型", "金额", "可用余额"].map((title) => (
                    <th key={title}>{title}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ledger.data?.items.map((row) => (
                  <tr key={row.id}>
                    <td>{new Date(row.created_at).toLocaleString("zh-CN")}</td>
                    <td>{row.title}</td>
                    <td>
                      <span className={`wallet-event ${row.event}`}>
                        {events[row.event]}
                      </span>
                    </td>
                    <td className="wallet-number">
                      {row.event === "consume"
                        ? "−"
                        : ["bonus", "recharge"].includes(row.event)
                          ? "+"
                          : ""}
                      {money(row.amount_cents)}
                    </td>
                    <td className="wallet-number">
                      {money(row.available_after_cents)}
                    </td>
                  </tr>
                ))}
                {!ledger.data?.items.length && (
                  <tr>
                    <td colSpan={5} className="wallet-empty">
                      暂无收支记录
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
        <nav className="wallet-pagination" aria-label="账单翻页">
          <span>
            共 {ledger.data?.total ?? 0} 条 · 第 {page} 页
          </span>
          <Button
            variant="outline"
            size="sm"
            className="button secondary small"
            aria-label="上一页"
            title="上一页"
            disabled={page <= 1 || ledger.isPending}
            onClick={() => setPage(page - 1)}
          >
            <ArrowLeft size={17} />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="button secondary small"
            aria-label="下一页"
            title="下一页"
            disabled={
              ledger.isPending || page * 20 >= (ledger.data?.total ?? 0)
            }
            onClick={() => setPage(page + 1)}
          >
            <ArrowRight size={17} />
          </Button>
        </nav>
      </section>
    </div>
  );
}
