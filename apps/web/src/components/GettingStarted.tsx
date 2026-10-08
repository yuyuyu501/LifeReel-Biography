import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "./ui/button";

const STEPS = [
  {
    title: "建立人物档案",
    text: "先记录要采访的家人。记不清的信息可以暂时留空。",
    to: "/people",
  },
  {
    title: "从一句话开始",
    text: "选择人物，用文字或录音讲一段经历。AI 根据资料空缺追问，也可以直接编辑人生资料表。",
    to: "/interviews",
  },
  {
    title: "直接对话纠正资料",
    text: "发现资料有误，直接告诉 AI 哪处不对、正确内容是什么。原对话保留，同一经历和记忆按明确的更正更新。",
    to: "/interviews",
  },
  {
    title: "用素材唤起回忆",
    text: "可选上传那个年代的照片或录音。先讲清人物、时间和地点，不必一次准备齐全。",
    to: "/interviews",
  },
  {
    title: "从资料写成人生书",
    text: "素材足够后，确认书籍目录与选材，生成约1000字的书章。可以手动编辑并保存版本。",
    to: "/books",
  },
  {
    title: "预览分镜再制作",
    text: "在影像页选择已保存书稿，先改编剧本与分镜。检查镜头要求和人物参考后，再单独生成影像。",
    to: "/studio",
  },
];

export function GettingStarted({ userId }: { userId: string }) {
  const key = "lifereel:guide:v2:" + userId;
  const [state, setState] = useState<{ step: number; hidden: boolean }>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) ?? "null");
      if (
        saved &&
        Number.isInteger(saved.step) &&
        saved.step >= 0 &&
        saved.step < STEPS.length
      )
        return { step: saved.step, hidden: Boolean(saved.hidden) };
    } catch {
      /* Keep the guide usable when browser storage is disabled. */
    }
    return { step: 0, hidden: false };
  });
  function save(step: number, hidden: boolean) {
    const next = { step, hidden };
    setState(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      /* Optional preference only. */
    }
  }
  if (state.hidden)
    return (
      <Button variant="link" onClick={() => save(state.step, false)}>
        重新打开使用教学
      </Button>
    );
  const step = STEPS[state.step];
  return (
    <section className="getting-started" aria-label="首次使用教学">
      <div>
        <small>
          使用教学 · {state.step + 1} / {STEPS.length}
        </small>
        <h2>{step.title}</h2>
        <p>{step.text}</p>
      </div>
      <div className="experience-actions">
        <Button asChild>
          <Link to={step.to}>去试一试</Link>
        </Button>
        {state.step > 0 && (
          <Button variant="outline" onClick={() => save(state.step - 1, false)}>
            上一步
          </Button>
        )}
        <Button
          variant="outline"
          onClick={() =>
            state.step === STEPS.length - 1
              ? save(0, true)
              : save(state.step + 1, false)
          }
        >
          {state.step === STEPS.length - 1 ? "完成教学" : "下一步"}
        </Button>
        <Button variant="link" onClick={() => save(state.step, true)}>
          暂时收起
        </Button>
      </div>
    </section>
  );
}
