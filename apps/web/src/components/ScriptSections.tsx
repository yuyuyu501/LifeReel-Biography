import type { ProductionRun, ScriptScene, ScriptShot } from "@lifereel/contracts";
import { useId } from "react";

const shotNames: Record<string, string> = {
  wide: "全景", medium: "中景", closeup: "特写", detail: "细节", archive: "档案镜头",
};

export function ScriptSections({ scene, shots = [], production }: {
  scene: ScriptScene;
  shots?: ScriptShot[];
  production?: ProductionRun["output_manifest"];
}) {
  const id = useId();
  const chapterShots = (scene.shots ?? shots.filter((shot) => shot.scene_id === scene.id))
    .slice().sort((a, b) => a.order_index - b.order_index);
  const lines = scene.dialogues?.length ? scene.dialogues
    : scene.narration ? [{ kind: "narration", speaker: "", text: scene.narration }] : [];
  const segments = production?.segments ?? [];
  return <div className="script-sections">
    <section aria-labelledby={`${id}-plot`}>
      <h4 id={`${id}-plot`}>剧情</h4>
      <p className={!scene.plot ? "script-section-empty" : undefined}>{scene.plot || "本章尚未记录独立的剧情概述"}</p>
    </section>
    <section aria-labelledby={`${id}-shots`}>
      <h4 id={`${id}-shots`}>分镜</h4>
      {chapterShots.length ? <ol className="script-shot-list">{chapterShots.map((shot, index) => <li key={shot.id}>
        <div className="script-shot-meta"><strong>镜头 {index + 1}</strong><span>{shotNames[shot.shot_type] ?? "镜头"}</span><span>{shot.duration_seconds} 秒</span></div>
        <p>{shot.visual_prompt}</p>
      </li>)}</ol> : <p className="script-section-empty">本章尚未记录分镜</p>}
      {!!segments.length && <div className="script-production-segments">
        <h5>本次制作分段</h5>
        {segments.map((segment, index) => <div className="script-production-segment" key={index}>
          <div className="script-shot-meta"><strong>第 {index + 1} 段</strong><span>{segment.duration_seconds} 秒</span></div>
          <p>{segment.visual_prompt || "尚未记录画面描述"}</p>
          {segment.prompt && <details><summary>实际生成提示词</summary><pre>{segment.prompt}</pre></details>}
        </div>)}
      </div>}
    </section>
    <section aria-labelledby={`${id}-dialogues`}>
      <h4 id={`${id}-dialogues`}>人物对话</h4>
      {lines.length ? <ol className="script-dialogue-list">{lines.map((line, index) => <li key={index}>
        <div className="script-dialogue-speaker"><strong>{line.speaker || "旁白"}</strong>{line.speaker && line.speaker !== "旁白" && <span>{line.kind === "narration" ? "旁白" : "对话"}</span>}</div>
        <p>{line.text}</p>
      </li>)}</ol> : <p className="script-section-empty">本章尚未记录对话或旁白</p>}
    </section>
    <section aria-labelledby={`${id}-setting`}>
      <h4 id={`${id}-setting`}>场景描述</h4>
      <p>{scene.visual_prompt || "本章尚未记录场景描述"}</p>
      {production?.plan?.continuity && <div className="script-production-setting"><h5>本次制作人物与环境</h5><p>{production.plan.continuity}</p></div>}
      {production?.plan?.voice && <div className="script-production-setting"><h5>本次制作声线</h5><p>{production.plan.voice}</p></div>}
    </section>
  </div>;
}
