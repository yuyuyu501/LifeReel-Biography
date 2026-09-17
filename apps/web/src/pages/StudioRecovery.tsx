import { Button } from "../components/ui/button";
import type { ProductionRun } from "@lifereel/contracts";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ImagePlus, Play } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, evidenceAssetUrl } from "../api/client";
import { ErrorNotice } from "../components/QueryState";

export function StudioRecovery({
  run,
  subjectId,
  canSpend,
  onSettled,
}: {
  run: ProductionRun;
  subjectId: string;
  canSpend: boolean;
  onSettled: () => Promise<void>;
}) {
  const [assetId, setAssetId] = useState("");
  const canRestore = run.recovery?.can_restore_original === true;
  const files = useQuery({
    queryKey: ["evidence", subjectId],
    queryFn: () => api.listEvidence(subjectId),
    enabled: !canRestore,
  });
  const candidates =
    files.data?.filter(
      (asset) =>
        asset.subject_id === subjectId &&
        asset.kind === "photo" &&
        !asset.is_redraw &&
        asset.status === "ready" &&
        ["image/jpeg", "image/png", "image/webp"].includes(asset.mime_type) &&
        asset.byte_size <= 10 * 1024 * 1024 &&
        !run.recovery?.rejected_asset_ids.includes(asset.id),
    ) ?? [];
  const selected = candidates.find((asset) => asset.id === assetId);
  const replace = useMutation({
    mutationFn: (id: string) => api.replaceProductionReference(run.id, id),
    onSettled,
  });
  const restore = useMutation({
    mutationFn: () => api.restoreProductionOriginal(run.id),
    onSettled,
  });

  if (canRestore)
    return (
      <section className="studio-recovery" aria-label="恢复连续生成">
        <h3>继续第 {(run.recovery?.segment_index ?? 0) + 1} 段</h3>
        <ErrorNotice error={restore.error} />
        <p className="studio-muted">已完成片段保留，使用原始素材继续生成。</p>
        <Button
          variant="default"
          size="sm"
          className="button primary small"
          disabled={!canSpend || restore.isPending}
          title={!canSpend ? "余额不足，请先充值" : undefined}
          onClick={() => restore.mutate()}
        >
          <Play size={15} aria-hidden="true" />{" "}
          {restore.isPending ? "正在提交" : "继续生成"}
        </Button>
      </section>
    );

  return (
    <section className="studio-recovery" aria-label="处理参考图">
      <h3>更换第 {(run.recovery?.segment_index ?? 0) + 1} 段参考图</h3>
      <ErrorNotice error={files.error || replace.error} />
      <p className="studio-muted">
        已完成片段保留，仅继续剩余片段。新参考图仍需通过平台审核。
      </p>
      {files.isPending ? (
        <p role="status">正在加载图片素材……</p>
      ) : candidates.length > 0 ? (
        <>
          <label className="studio-version">
            参考图片
            <select
              value={selected?.id ?? ""}
              onChange={(event) => setAssetId(event.target.value)}
              disabled={replace.isPending}
            >
              <option value="">选择另一张图片</option>
              {candidates.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.original_filename}
                </option>
              ))}
            </select>
          </label>
          {selected && (
            <img
              className="studio-reference-preview"
              src={evidenceAssetUrl(selected.id)}
              alt={`参考图：${selected.original_filename}`}
            />
          )}
          <Button
            variant="default"
            size="sm"
            className="button primary small"
            disabled={!selected || !canSpend || replace.isPending}
            title={!canSpend ? "余额不足，请先充值" : undefined}
            onClick={() => selected && replace.mutate(selected.id)}
          >
            <Play size={15} aria-hidden="true" />{" "}
            {replace.isPending ? "正在提交" : "使用此图继续生成"}
          </Button>
        </>
      ) : (
        !files.isError && <p className="studio-muted">暂无可用的图片素材</p>
      )}
      <Link className="studio-material-link" to="/interviews">
        <ImagePlus size={16} aria-hidden="true" /> 前往采访添加素材
      </Link>
    </section>
  );
}
