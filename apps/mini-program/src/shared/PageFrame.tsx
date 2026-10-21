import {
  useEffect,
  useRef,
  useState,
  type PropsWithChildren,
  type ReactNode,
} from "react";
import { Button, Text, View } from "@tarojs/components";
import Taro, { useDidHide, useDidShow } from "@tarojs/taro";
import { Icon, type IconName } from "./Icon";
import { PreviewNotice } from "./PreviewNotice";
import { GuidedTour } from "./GuidedTour";
import type { TutorialConfig } from "./tutorial";
import { getStored, store } from "./platform";

let frameSequence = 0;

const tabs: { key: string; label: string; icon: IconName; path: string }[] = [
  { key: "home", label: "家人", icon: "users", path: "home" },
  { key: "interview", label: "采访", icon: "mic", path: "interview" },
  { key: "books", label: "写书", icon: "book", path: "books" },
  { key: "production", label: "影像", icon: "film", path: "production" },
];

export function PageFrame({
  children,
  title,
  subtitle,
  active,
  subjectId = "",
  action,
  locked = false,
  className = "",
  tutorial,
}: PropsWithChildren<{
  title: string;
  subtitle?: string;
  active: string;
  subjectId?: string;
  action?: ReactNode;
  locked?: boolean;
  className?: string;
  tutorial?: TutorialConfig;
}>) {
  const [frameId] = useState(() => `guide-page-${++frameSequence}`);
  const [guideOpen, setGuideOpen] = useState(false);
  const [visible, setVisible] = useState(true);
  const autoOpened = useRef(false);
  const guideKey = `lifereel:tutorial:v1:${active}`;
  useDidShow(() => setVisible(true));
  useDidHide(() => {
    setVisible(false);
    setGuideOpen(false);
  });
  useEffect(() => {
    if (!tutorial?.ready || locked || !visible || autoOpened.current) return;
    autoOpened.current = true;
    try {
      if (getStored(guideKey)) return;
    } catch {
      // Storage restrictions must not prevent the tutorial or normal navigation.
    }
    setGuideOpen(true);
  }, [tutorial?.ready, locked, visible, guideKey]);

  function navigate(tab: (typeof tabs)[number]) {
    if (tab.key === active) return;
    if (locked) {
      void Taro.showToast({ title: "请先完成当前编辑或操作", icon: "none" });
      return;
    }
    if (tab.key !== "home" && !subjectId) {
      void Taro.showToast({ title: "请先选择一位家人", icon: "none" });
      return;
    }
    void Taro.reLaunch({
      url: `/pages/${tab.path}/index${subjectId ? `?subjectId=${encodeURIComponent(subjectId)}` : ""}`,
    });
  }
  return (
    <View className={`page ${className}`} id={frameId}>
      <View className="brand-bar">
        <View className="brand-name">
          <Text className="brand-mark">岁</Text>
          <Text>岁忆影传</Text>
        </View>
        <View className="privacy-label">
          <Icon name="lock" tone="muted" />
          <Text>家庭私密空间</Text>
        </View>
      </View>
      <PreviewNotice />
      <View className="page-heading">
        <View className="heading-copy">
          <Text className="title">{title}</Text>
          {subtitle && <Text className="description">{subtitle}</Text>}
        </View>
        <View className="heading-actions">
          {tutorial && (
            <Button
              id={`guide-help-${active}`}
              className="icon-button"
              aria-label="查看新手引导"
              disabled={!tutorial.ready || locked}
              onClick={() => {
                void Taro.hideKeyboard().catch(() => undefined);
                setGuideOpen(true);
              }}
            >
              <Icon name="help" />
            </Button>
          )}
          {action}
        </View>
      </View>
      {guideOpen && visible && tutorial && (
        <GuidedTour
          frame={`#${frameId}`}
          steps={tutorial.steps}
          onClose={(result) => {
            if (result !== "unavailable") {
              try {
                store(guideKey, result);
              } catch {
                // Closing remains possible when local storage is unavailable.
              }
            }
            setGuideOpen(false);
          }}
        />
      )}
      {children}
      <View className="bottom-navigation">
        {tabs.map((tab) => (
          <Button
            key={tab.key}
            className={`nav-item ${active === tab.key ? "is-active" : ""}`}
            onClick={() => navigate(tab)}
          >
            <Icon
              name={tab.icon}
              tone={active === tab.key ? "green" : "muted"}
            />
            <Text>{tab.label}</Text>
          </Button>
        ))}
      </View>
    </View>
  );
}
