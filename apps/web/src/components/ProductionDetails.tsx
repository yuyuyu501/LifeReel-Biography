import type { ProductionRun } from "@lifereel/contracts";
import { ScriptSections } from "./ScriptSections";

export function ProductionDetails({ run }: { run: ProductionRun }) {
  const production = run.output_manifest;
  if (!production) return null;
  const snapshot = production.script_snapshot?.[0];
  return <section className="studio-production-info" aria-label="本次制作">
    <h3>本次制作</h3>
    {snapshot && <details><summary>生成时剧本（只读）</summary><ScriptSections scene={snapshot} /></details>}
    {!!production.segments?.length && <div className="script-production-segments">
      <h4>制作分段</h4>
      {production.segments.map((segment, index) => <div className="script-production-segment" key={index}>
        <div className="script-shot-meta"><strong>第 {index + 1} 段</strong><span>{segment.duration_seconds} 秒</span></div>
        <p>{segment.visual_prompt || "尚未记录画面描述"}</p>
        {segment.prompt && <details><summary>实际生成提示词</summary><pre>{segment.prompt}</pre></details>}
      </div>)}
    </div>}
    {production.plan?.continuity && <div className="script-production-setting"><h4>人物与环境</h4><p>{production.plan.continuity}</p></div>}
    {production.plan?.voice && <div className="script-production-setting"><h4>声线</h4><p>{production.plan.voice}</p></div>}
  </section>;
}
