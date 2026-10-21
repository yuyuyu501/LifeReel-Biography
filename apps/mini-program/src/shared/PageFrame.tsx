import type { PropsWithChildren, ReactNode } from "react";
import { Button, Text, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { Icon, type IconName } from "./Icon";
import { PreviewNotice } from "./PreviewNotice";

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
}: PropsWithChildren<{
  title: string;
  subtitle?: string;
  active: string;
  subjectId?: string;
  action?: ReactNode;
  locked?: boolean;
  className?: string;
}>) {
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
    <View className={`page ${className}`}>
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
        {action}
      </View>
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
