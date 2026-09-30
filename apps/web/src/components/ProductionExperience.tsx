import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  ProductionRun,
  ScriptScene,
  ScriptShot,
} from "@lifereel/contracts";
import { api, productionReviewUrl, productionSegmentUrl } from "../api/client";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "./ui/dialog";
import { ErrorNotice } from "./QueryState";

export function ShotPreview({
  scene,
  projectShots = [],
}: {
  scene: ScriptScene;
  projectShots?: ScriptShot[];
}) {
  const shots = (
    scene.shots ?? projectShots.filter((shot) => shot.scene_id === scene.id)
  )
    .slice()
    .sort((a, b) => a.order_index - b.order_index);
  return (
    <section className="shot-preview" aria-label="分镜预览">
      <h3>逐镜头预览</h3>
      <p className="studio-muted">
        检查每个镜头的叙事作用、画面差异和人物要求；需要调整时可在剧本中编辑。
      </p>
      {shots.map((shot, i) => (
        <article key={shot.id}>
          <h4>
            镜头 {i + 1} · {shot.duration_seconds} 秒 · {shot.shot_type}
          </h4>
          <p>{shot.visual_prompt}</p>
          {i > 0 &&
            shot.visual_prompt.replace(/\s/g, "") ===
              shots[i - 1].visual_prompt.replace(/\s/g, "") && (
              <p role="status">
                与上一镜头画面描述相同，建议调整构图、动作或叙事作用。
              </p>
            )}
        </article>
      ))}
      {!shots.length && <p>分镜尚未生成。</p>}
    </section>
  );
}

export function ProductionWait({ run }: { run: ProductionRun }) {
  const progress = useQuery({
    queryKey: ["production-progress", run.id],
    queryFn: () => api.productionProgress(run.id),
    refetchInterval: 5000,
  });
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const seconds = progress.data
    ? progress.data.elapsed_seconds +
      Math.max(0, Math.floor((now - progress.dataUpdatedAt) / 1000))
    : Math.max(0, Math.floor((now - Date.parse(run.created_at)) / 1000));
  const estimate = progress.data?.estimated_seconds;
  return (
    <p className="studio-muted">
      已等待 {Math.floor(seconds / 60)} 分 {seconds % 60} 秒。
      {estimate
        ? "相似任务通常总耗时 " +
          estimate[0] +
          "–" +
          estimate[1] +
          " 秒（" +
          progress.data?.sample_count +
          " 次历史样本，非倒计时）。"
        : "同模型、时长和处理方式的完成样本不足，暂不显示预计完成时间。"}
    </p>
  );
}

function RegenerationDialog({
  run,
  index,
  close,
}: {
  run: ProductionRun;
  index: number;
  close: () => void;
}) {
  const client = useQueryClient();
  const [requestId] = useState(() => crypto.randomUUID());
  const quote = useQuery({
    queryKey: ["segment-quote", run.id, index],
    queryFn: () => api.segmentQuote(run.id, index),
    retry: false,
  });
  const regenerate = useMutation({
    mutationFn: () =>
      api.regenerateSegment(run.id, index, {
        request_id: requestId,
        expected_script_version: quote.data!.script_version,
        quoted_amount_cents: quote.data!.amount_cents,
      }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["production-runs"] }),
        client.invalidateQueries({ queryKey: ["wallet"] }),
      ]);
      close();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !regenerate.isPending) close();
      }}
    >
      <DialogContent
        showCloseButton={!regenerate.isPending}
        aria-describedby="regeneration-description"
      >
        <DialogTitle>重做第 {index + 1} 镜头</DialogTitle>
        <p id="regeneration-description">
          使用本次成片的原剧本和参考素材重新生成此镜头，其余镜头复用。保留原成片，完成后请核对人物外貌及前后衔接。
        </p>
        <ErrorNotice error={quote.error || regenerate.error} />
        {quote.isPending && <p>正在获取报价…</p>}
        {quote.data && (
          <p>
            {quote.data.video_billing_mode === "tokens"
              ? "预留额度 ¥"
              : "本镜头费用 ¥"}
            {(quote.data.amount_cents / 100).toFixed(2)} ·{" "}
            {quote.data.target_seconds} 秒
            {quote.data.video_billing_mode === "tokens"
              ? "；仅按新调用实际用量结算，其余镜头不重复收费。"
              : "；其余镜头不重复收费。"}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            disabled={regenerate.isPending}
            onClick={close}
          >
            取消
          </Button>
          <Button
            disabled={!quote.data || regenerate.isPending}
            onClick={() => regenerate.mutate()}
          >
            {regenerate.isPending ? "提交中…" : "确认重做"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ProductionQuality({
  run,
  disabled,
}: {
  run: ProductionRun;
  disabled?: boolean;
}) {
  const [target, setTarget] = useState<number | null>(null);
  const manifest = run.output_manifest;
  const segments = manifest?.segments ?? [];
  if (!segments.length || manifest?.media_retention) return null;
  return (
    <section className="shot-preview" aria-label="逐镜头验收">
      <h3>逐镜头验收</h3>
      <p className="studio-muted">
        抽帧来自实际生成的视频。请核对同一人物的脸型、五官、年龄和服装，再播放检查动作、声音及镜头衔接；参考一致不代表画面已经验收通过。
      </p>
      {!!manifest?.quality_review?.duplicate_video_segments?.length && (
        <p className="notice error">
          检测到完全相同的视频片段，请检查并重做重复镜头。
        </p>
      )}
      {!!manifest?.quality_review?.shot_warnings?.length && (
        <p role="status">部分相邻分镜描述相似，请核对是否需要增加画面差异。</p>
      )}
      {segments.map((segment, i) => (
        <article key={i}>
          <h4>
            镜头 {i + 1} · {segment.duration_seconds} 秒
            {segment.reused ? " · 复用" : ""}
          </h4>
          <p>{segment.visual_prompt}</p>
          <p className="studio-muted">
            {segment.identity_reference_ids?.length
              ? "使用本章固定人物参考"
              : "未记录固定人物参考，请核对形象一致性"}
          </p>
          <div className="shot-review-frames">
            {segment.review_frames?.map((frame) => (
              <figure key={frame.position}>
                <img
                  loading="lazy"
                  src={productionReviewUrl(run.id, i, frame.position)}
                  alt={
                    "镜头 " + (i + 1) + " 实际画面 " + frame.at_seconds + " 秒"
                  }
                />
                <figcaption>{frame.at_seconds} 秒</figcaption>
              </figure>
            ))}
          </div>
          {segment.status === "completed" && (
            <>
              {!segment.review_frames?.length && (
                <p>尚无验收抽帧，请播放此片段检查。</p>
              )}
              <details>
                <summary>播放此镜头</summary>
                <video
                  controls
                  preload="none"
                  src={productionSegmentUrl(run.id, i)}
                  aria-label={"验收镜头 " + (i + 1)}
                />
              </details>
            </>
          )}
          {run.status === "completed" &&
            manifest?.generation_config?.mode === "segmented" && (
              <Button
                variant="outline"
                disabled={disabled}
                onClick={() => setTarget(i)}
              >
                重做第 {i + 1} 镜头
              </Button>
            )}
        </article>
      ))}
      {target !== null && (
        <RegenerationDialog
          key={run.id + ":" + target}
          run={run}
          index={target}
          close={() => setTarget(null)}
        />
      )}
    </section>
  );
}
