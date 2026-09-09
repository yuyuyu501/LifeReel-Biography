import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { money } from "../pages/WalletPage";

export function ScriptPriceNotice() {
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: api.wallet });
  if (!wallet.data?.prices) return null;
  return <p className="wallet-note">每章每次成功生成或更新 {money(wallet.data.prices.script_chapter_cents)}，含采访追问、记忆与知识图谱整理及素材理解；采访自动更新同价。剧本未生成成功不扣款，同一次请求重试不重复收费。<Link to="/wallet">查看钱包</Link></p>;
}
