import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { money } from "../pages/WalletPage";

export function ScriptPriceNotice() {
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: api.wallet });
  if (!wallet.data?.prices) return null;
  if (wallet.data.prices.script_billing_mode === "tokens") {
    return <p className="wallet-note">采访、追问、记忆整理及剧本按实际 AI 用量计费，价格为官方标准价的 1.5 倍；未生成剧本也会产生用量费用，不再按章收费。不足一分钱的费用累计结算。<Link to="/wallet">查看钱包</Link></p>;
  }
  return <p className="wallet-note">每章每次成功生成或更新 {money(wallet.data.prices.script_chapter_cents)}，含采访追问、记忆与知识图谱整理及素材理解；采访自动更新同价。剧本未生成成功不扣款，同一次请求重试不重复收费。<Link to="/wallet">查看钱包</Link></p>;
}
