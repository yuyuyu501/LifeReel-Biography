import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, CreditCard, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { QueryState } from "../components/QueryState";

export const money = (cents: number) => `¥${(cents / 100).toFixed(2)}`;
const events: Record<string, string> = { bonus: "赠送", reserve: "冻结", consume: "消费", release: "解冻" };

export function WalletPage() {
  const client = useQueryClient();
  const [event, setEvent] = useState("");
  const [page, setPage] = useState(1);
  const [amount, setAmount] = useState(100);
  const [customAmount, setCustomAmount] = useState("");
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: api.wallet, refetchInterval: 10000 });
  const ledger = useQuery({ queryKey: ["wallet-ledger", page, event], queryFn: () => api.walletLedger(page, event) });
  const w = wallet.data;
  return <div className="page wallet-page">
    <header className="page-title-row"><div><span className="eyebrow">家庭账户</span><h1>钱包</h1></div></header>
    <QueryState queries={[wallet]} />
    {w && <>
      <section className="wallet-summary" aria-label="钱包余额">
        <div className="wallet-available"><span>可用余额</span><strong>{money(w.available_cents)}</strong></div>
      </section>
      <section className="wallet-recharge" aria-labelledby="recharge-title">
        <div><h2 id="recharge-title">在线充值</h2></div>
        <fieldset><legend>支付金额</legend>
          <div className="wallet-amounts">{[10, 50, 100, 200].map(value => <div key={value} className={amount === value ? "selected" : ""} onClick={() => setAmount(value)}>{money(value * 100)}</div>)}
          <div className={amount === -1 ? "selected" : ""} onClick={() => setAmount(-1)}>其它金额</div></div>{amount === -1 && <input className="wallet-custom-amount" type="number" min="1" step="1" value={customAmount} onChange={event => setCustomAmount(event.target.value)} placeholder="输入金额（元）" aria-label="自定义充值金额" />}</fieldset>
        <fieldset><legend>支付方式</legend>
          <div className="wallet-pay-methods"><div className="selected">微信支付</div></div>
        </fieldset>
        <div className="wallet-actions"><button className="button primary" disabled><CreditCard size={17} />确认支付</button></div>
      </section>
      <div className="wallet-rates"><span>当前价格</span><span>影像 {money(w.prices.video_cents_per_second)} / 秒（{money(w.prices.video_cents_per_second * 30)} / 30 秒）</span><span>剧本 {money(w.prices.script_chapter_cents)} / 章 / 次</span><span>每次成功生成或更新均计费，含采访自动更新、追问、记忆与知识图谱整理及素材理解</span></div>
    </>}
    <section className="wallet-history" aria-label="钱包明细">
      <div className="wallet-history-bar"><strong>消费明细</strong><label>类型<select value={event} onChange={e => { setEvent(e.target.value); setPage(1); }}><option value="">全部</option>{Object.entries(events).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
      <QueryState queries={[ledger]} />
      {ledger.isSuccess && <div className="wallet-table-scroll"><table className="wallet-table"><thead><tr>
        {["时间", "事项", "类型", "金额", "可用余额"].map(title => <th key={title}>{title}</th>)}
      </tr></thead><tbody>
        {ledger.data?.items.map(row => <tr key={row.id}><td>{new Date(row.created_at).toLocaleString("zh-CN")}</td><td>{row.title}</td><td><span className={`wallet-event ${row.event}`}>{events[row.event]}</span></td><td className="wallet-number">{row.event === "consume" ? "−" : row.event === "bonus" ? "+" : ""}{money(row.amount_cents)}</td><td className="wallet-number">{money(row.available_after_cents)}</td></tr>)}
        {!ledger.data?.items.length && <tr><td colSpan={5} className="wallet-empty">暂无收支记录</td></tr>}
      </tbody></table></div>}
      <nav className="wallet-pagination" aria-label="账单翻页"><span>共 {ledger.data?.total ?? 0} 条 · 第 {page} 页</span><button className="button secondary small" aria-label="上一页" title="上一页" disabled={page <= 1 || ledger.isPending} onClick={() => setPage(page - 1)}><ArrowLeft size={17} /></button><button className="button secondary small" aria-label="下一页" title="下一页" disabled={ledger.isPending || page * 20 >= (ledger.data?.total ?? 0)} onClick={() => setPage(page + 1)}><ArrowRight size={17} /></button></nav>
    </section>
  </div>;
}
