import type { ScriptProject } from "@lifereel/contracts";

const roleLabels: Record<string, string> = {
  opening: "开场",
  setup: "铺垫",
  development: "发展",
  turning_point: "转折",
  aftermath: "余波",
  closing: "收束",
  transition: "转场",
  montage: "蒙太奇",
};

export function ScriptPlanSummary({ project }: { project: ScriptProject }) {
  const brief = project.adaptation_brief;
  const bible = project.story_bible;
  const sequence = project.sequence_plan?.items ?? [];
  if (!brief && !bible && !sequence.length) return null;

  return (
    <details className="script-plan-summary">
      <summary>改编规划</summary>
      <div className="script-plan-summary-body">
        {brief && (
          <section aria-labelledby="script-plan-theme">
            <h4 id="script-plan-theme">改编简报</h4>
            <p>{brief.theme}</p>
            {brief.dramatic_question && <p>{brief.dramatic_question}</p>}
            {brief.tone && <small>基调：{brief.tone}</small>}
            {brief.must_avoid.length > 0 && (
              <small>限制：{brief.must_avoid.join("；")}</small>
            )}
          </section>
        )}
        {sequence.length > 0 && (
          <section aria-labelledby="script-plan-sequence">
            <h4 id="script-plan-sequence">场次计划</h4>
            <ol>
              {sequence.map((item) => (
                <li key={item.key}>
                  <strong>
                    {item.order_index}. {item.title}
                  </strong>
                  <span>{roleLabels[item.narrative_role] ?? item.narrative_role}</span>
                  <p>{item.summary}</p>
                </li>
              ))}
            </ol>
          </section>
        )}
        {bible && (
          <section aria-labelledby="script-plan-bible">
            <h4 id="script-plan-bible">故事圣经</h4>
            <p>
              人物 {bible.characters.length} · 地点 {bible.locations.length} ·
              时间线 {bible.timeline.length} · 关键物件 {bible.key_objects.length}
            </p>
            {bible.constraints.length > 0 && (
              <small>连续性约束：{bible.constraints.join("；")}</small>
            )}
          </section>
        )}
      </div>
    </details>
  );
}
