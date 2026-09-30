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
    text: "选一个人生章节，用文字或录音回答。简短回答也可以，采访会继续追问具体细节。",
    to: "/interviews",
  },
  {
    title: "直接对话纠正剧本",
    text: "发现剧本有误，直接告诉 AI 哪处不对、正确内容是什么。原对话保留，记忆和本章剧本按明确的更正更新。",
    to: "/interviews",
  },
  {
    title: "用素材唤起回忆",
    text: "可选上传那个年代的照片或录音。先讲清人物、时间和地点，不必一次准备齐全。",
    to: "/interviews",
  },
  {
    title: "查看并补充剧本",
    text: "初稿生成后仍能继续讲。确认叙事内容，再选择获授权的照片或音频作为本章参考。",
    to: "/scripts",
  },
  {
    title: "预览分镜再制作",
    text: "检查各镜头的内容和人物参考。人物形象保持一致，画面可以变化；确认费用后再生成影像。",
    to: "/studio",
  },
];

export function GettingStarted({ userId }: { userId: string }) {
  const key = "lifereel:guide:v1:" + userId;
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
