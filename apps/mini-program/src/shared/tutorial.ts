export type TutorialStep = {
  target: string;
  title: string;
  description: string;
};

export type TutorialConfig = {
  ready: boolean;
  steps: TutorialStep[];
};

export type TutorialRect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

const clamp = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), Math.max(min, max));

export function tutorialLayout(
  target: TutorialRect | null,
  frame: TutorialRect,
  viewport: { width: number; height: number; bottomInset: number },
  panelHeight: number,
) {
  const edge = 12;
  const bottom = viewport.height - viewport.bottomInset - edge;
  const frameLeft = Math.max(0, frame.left);
  const frameRight = Math.min(viewport.width, frame.left + frame.width);
  const width = Math.min(360, frameRight - frameLeft - edge * 2);
  const left = clamp(
    target ? target.left + target.width / 2 - width / 2 : frameLeft,
    frameLeft + edge,
    frameRight - width - edge,
  );
  let spotlight: TutorialRect | null = null;
  if (target && target.width > 0 && target.height > 0) {
    const x = Math.max(frameLeft + 4, target.left - 6);
    const y = Math.max(4, target.top - 6);
    const right = Math.min(frameRight - 4, target.left + target.width + 6);
    const lower = Math.min(bottom + 4, target.top + target.height + 6);
    if (right > x && lower > y)
      spotlight = { left: x, top: y, width: right - x, height: lower - y };
  }
  const availableBelow = spotlight
    ? bottom - spotlight.top - spotlight.height - edge
    : 0;
  const availableAbove = spotlight ? spotlight.top - edge * 2 : 0;
  let side: "above" | "below" | "center" = "center";
  let maxHeight = bottom - edge;
  let top = Math.max(edge, (bottom - Math.min(panelHeight, maxHeight)) / 2);
  if (spotlight && Math.max(availableBelow, availableAbove) >= 160) {
    side =
      availableBelow >= panelHeight || availableBelow >= availableAbove
        ? "below"
        : "above";
    maxHeight = side === "below" ? availableBelow : availableAbove;
    top =
      side === "below"
        ? spotlight.top + spotlight.height + edge
        : spotlight.top - edge - Math.min(panelHeight, maxHeight);
  } else {
    spotlight = null;
  }
  return {
    spotlight,
    panel: { left, top, width, maxHeight },
    side,
    pointerLeft: clamp(
      target ? target.left + target.width / 2 - left : width / 2,
      20,
      width - 20,
    ),
  };
}
