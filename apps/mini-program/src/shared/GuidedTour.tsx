import { useEffect, useRef, useState } from "react";
import { Button, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { Icon } from "./Icon";
import {
  tutorialLayout,
  type TutorialRect,
  type TutorialStep,
} from "./tutorial";

type Measurement = {
  target: TutorialRect | null;
  frame: TutorialRect;
  scrollTop: number;
  panelHeight: number;
};

function measure(frame: string, target: string): Promise<Measurement> {
  return new Promise((resolve) => {
    const query = Taro.createSelectorQuery();
    query.select(`${frame} ${target}`).boundingClientRect();
    query.select(frame).boundingClientRect();
    query.selectViewport().scrollOffset();
    query.select(`${frame} .tour-panel`).boundingClientRect();
    query.exec(([rect, bounds, scroll, panel]) =>
      resolve({
        target: rect,
        frame: bounds,
        scrollTop: scroll?.scrollTop || 0,
        panelHeight: panel?.height || 220,
      }),
    );
  });
}

export function GuidedTour({
  frame,
  steps,
  onClose,
}: {
  frame: string;
  steps: TutorialStep[];
  onClose: (result: "completed" | "skipped" | "unavailable") => void;
}) {
  const [available, setAvailable] = useState<TutorialStep[]>([]);
  const [index, setIndex] = useState(0);
  const [position, setPosition] = useState<Measurement | null>(null);
  const [panelHeight, setPanelHeight] = useState(220);
  const [resizing, setResizing] = useState(0);
  const [moving, setMoving] = useState(true);
  const close = useRef(onClose);
  close.current = onClose;
  const initialSteps = useRef(steps);
  const info = Taro.getSystemInfoSync();
  const viewport = {
    width: info.windowWidth,
    height: info.windowHeight,
    bottomInset: Math.max(
      0,
      Math.min(
        40,
        info.screenHeight - (info.safeArea?.bottom || info.screenHeight),
      ),
    ),
  };
  const layout = tutorialLayout(
    position?.target || null,
    position?.frame || {
      left: 0,
      top: 0,
      width: viewport.width,
      height: viewport.height,
    },
    viewport,
    panelHeight,
  );
  const step = available[index];

  useEffect(() => {
    let active = true;
    Taro.nextTick(() => {
      const query = Taro.createSelectorQuery();
      initialSteps.current.forEach((item) =>
        query.select(`${frame} ${item.target}`).boundingClientRect(),
      );
      query.exec((rectangles) => {
        if (!active) return;
        const visible = initialSteps.current.filter(
          (_, i) => rectangles[i]?.width > 0 && rectangles[i]?.height > 0,
        );
        if (!visible.length) {
          close.current("unavailable");
          void Taro.showToast({
            title: "页面准备好后可重新查看引导",
            icon: "none",
          });
        } else setAvailable(visible);
      });
    });
    const resize = () => setResizing((value) => value + 1);
    Taro.onWindowResize(resize);
    return () => {
      active = false;
      Taro.offWindowResize(resize);
    };
  }, [frame]);

  useEffect(() => {
    if (!step) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setMoving(true);
    setPosition(null);
    async function locate() {
      try {
        let value = await measure(frame, step.target);
        if (!active) return;
        if (value.target) {
          const rect = value.target;
          if (rect.top < 16 || rect.top + rect.height > viewport.height - 90) {
            await Taro.pageScrollTo({
              scrollTop: Math.max(
                0,
                value.scrollTop +
                  rect.top -
                  Math.max(64, viewport.height * 0.22),
              ),
              duration: 0,
            });
            // Native layout and H5 scrolling settle after the scroll promise.
            await new Promise((resolve) => {
              timer = setTimeout(resolve, 80);
            });
            if (!active) return;
            value = await measure(frame, step.target);
          }
        }
        if (active) {
          setPanelHeight(value.panelHeight);
          setPosition(value);
        }
      } catch {
        if (active) close.current("unavailable");
      } finally {
        if (active) setMoving(false);
      }
    }
    Taro.nextTick(() => void locate());
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [frame, step, resizing, viewport.height]);

  const spot = moving ? null : layout.spotlight;
  const blocks = spot
    ? [
        { left: 0, top: 0, width: viewport.width, height: spot.top },
        { left: 0, top: spot.top, width: spot.left, height: spot.height },
        {
          left: spot.left + spot.width,
          top: spot.top,
          width: viewport.width - spot.left - spot.width,
          height: spot.height,
        },
        {
          left: 0,
          top: spot.top + spot.height,
          width: viewport.width,
          height: viewport.height - spot.top - spot.height,
        },
      ]
    : [{ left: 0, top: 0, width: viewport.width, height: viewport.height }];
  const pixels = (rect: Record<string, number>) =>
    Object.fromEntries(
      Object.entries(rect).map(([key, value]) => [key, `${value}px`]),
    );
  function moveTo(next: number) {
    setMoving(true);
    setPosition(null);
    setIndex(next);
  }

  return (
    <View
      className={`guided-tour ${moving ? "is-locating" : "is-ready"}`}
      catchMove
      onTouchMove={(event) => {
        event.stopPropagation();
        event.preventDefault();
      }}
    >
      {blocks.map((block, i) => (
        <View className="tour-mask" style={pixels(block)} key={i} />
      ))}
      {spot && <View className="tour-spotlight" style={pixels(spot)} />}
      {spot && layout.side !== "center" && (
        <View
          className="tour-pointer"
          style={{
            left: `${layout.panel.left + layout.pointerLeft}px`,
            top: `${layout.side === "below" ? layout.panel.top - 6 : layout.panel.top + Math.min(panelHeight, layout.panel.maxHeight) - 6}px`,
          }}
        />
      )}
      <View
        className="tour-panel"
        aria-role="dialog"
        aria-label="新手引导"
        style={pixels(layout.panel)}
      >
        <View className="tour-heading">
          <Text className="tour-counter">
            新手引导{step ? ` · ${index + 1} / ${available.length}` : ""}
          </Text>
          <Button
            className="text-button tour-skip"
            onClick={() => onClose("skipped")}
          >
            跳过
          </Button>
        </View>
        <Text className="tour-title">{step?.title || "正在准备引导"}</Text>
        <Text className="tour-description">
          {step?.description || "正在定位操作位置……"}
        </Text>
        <View className="tour-actions">
          {index > 0 && (
            <Button
              className="secondary-button"
              disabled={moving}
              onClick={() => moveTo(index - 1)}
            >
              <Icon name="back" />
              上一步
            </Button>
          )}
          <Button
            className="primary-button"
            disabled={moving || !step}
            onClick={() => {
              if (index === available.length - 1) onClose("completed");
              else moveTo(index + 1);
            }}
          >
            {index === available.length - 1 ? "开始使用" : "下一步"}
            <Icon
              name={index === available.length - 1 ? "check" : "arrow"}
              tone="white"
            />
          </Button>
        </View>
      </View>
    </View>
  );
}
