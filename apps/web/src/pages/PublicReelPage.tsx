import { useQuery } from "@tanstack/react-query";
import { BookHeart, ShieldCheck } from "lucide-react";
import { useParams } from "react-router-dom";
import { api, publicContentUrl } from "../api/client";
import { statusLabel } from "../statusLabels";

export function PublicReelPage() {
  const { token = "" } = useParams();
  const publication = useQuery({
    queryKey: ["public-reel", token],
    queryFn: () => api.publicPublication(token),
    enabled: Boolean(token),
    retry: false,
  });

  if (publication.isLoading) return <div className="public-reel"><p>正在打开影传……</p></div>;
  if (!publication.data) return <div className="public-reel"><h1>这部影传暂时无法访问</h1><p>它可能已经被主人撤回。</p></div>;
  return (
    <main className="public-reel">
      <div className="public-brand"><BookHeart size={24} /> 岁忆影传</div>
      <span className="eyebrow">一份经过授权的生命影像</span>
      <h1>家庭影传</h1>
      <p className="lead">这份内容按照“{statusLabel(publication.data.audience)}”范围发布。未经主人许可，请勿再次传播或用于训练、广告和身份仿冒。</p>
      <video controls playsInline preload="metadata" src={publicContentUrl(token)} />
      <div className="public-safety"><ShieldCheck size={18} /> 主人可随时撤回；撤回后此链接立即失效。</div>
    </main>
  );
}
