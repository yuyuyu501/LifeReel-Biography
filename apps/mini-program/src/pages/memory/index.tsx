import { useEffect, useState } from "react";
import { Text, View } from "@tarojs/components";
import { getCurrentInstance } from "@tarojs/taro";
import type {
  MemoryClaim,
  MemoryConflict,
  MemoryEntity,
  MemoryOverview,
  TimelineAnchor,
} from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { PageFrame } from "../../shared/PageFrame";

export default function MemoryPage() {
  const subjectId = getCurrentInstance().router?.params?.subjectId || "";
  const [overview, setOverview] = useState<MemoryOverview | null>(null);
  const [claims, setClaims] = useState<MemoryClaim[]>([]);
  const [entities, setEntities] = useState<MemoryEntity[]>([]);
  const [timeline, setTimeline] = useState<TimelineAnchor[]>([]);
  const [conflicts, setConflicts] = useState<MemoryConflict[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!subjectId) return;
    Promise.all([
      miniApi.memoryOverview(subjectId),
      miniApi.memories(subjectId),
      miniApi.entities(subjectId),
      miniApi.timeline(subjectId),
      miniApi.conflicts(subjectId),
    ])
      .then(([summary, memoryClaims, people, dates, openConflicts]) => {
        setOverview(summary);
        setClaims(memoryClaims);
        setEntities(people);
        setTimeline(dates);
        setConflicts(openConflicts);
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "记忆加载失败"),
      );
  }, [subjectId]);

  return (
    <PageFrame
      title="记忆档案"
      subtitle="那些人，那些年，那些事。"
      active="memory"
      subjectId={subjectId}
      tutorial={{
        ready: !!overview,
        steps: [
          {
            target: "#guide-memory-timeline",
            title: "按时间回看经历",
            description:
              "这里按时间排列已经记录的事件，可以与家人的讲述一起核对。",
          },
          {
            target: "#guide-memory-facts",
            title: "查看事实和原话出处",
            description:
              "每条事实旁会保留来源。发现遗漏或错误，可回到采访继续补充，或到人生资料中更正。",
          },
          {
            target: "#guide-memory-conflicts",
            title: "留意待核对的记录",
            description:
              "存在不同说法时，这里会提示需要核对的内容。确认正确说法后，再继续写书或改编。",
          },
        ],
      }}
    >
      {error ? <Text className="error">{error}</Text> : null}
      {overview ? (
        <View className="stats-grid">
          <View className="stat-card">
            <Text className="stat-value">{overview.claim_count}</Text>
            <Text className="stat-label">记忆事实</Text>
          </View>
          <View className="stat-card">
            <Text className="stat-value">{overview.timeline_count}</Text>
            <Text className="stat-label">时间节点</Text>
          </View>
          <View className="stat-card">
            <Text className="stat-value">{overview.open_conflict_count}</Text>
            <Text className="stat-label">待核对冲突</Text>
          </View>
        </View>
      ) : null}
      <View className="section">
        <Text className="section-title" id="guide-memory-timeline">
          时间线
        </Text>
        {timeline.length ? (
          timeline.map((item) => (
            <View className="timeline-item" key={item.id}>
              <Text className="list-title">
                {item.year || item.time_text || "未标注时间"}
              </Text>
              <Text className="list-meta">{item.event_text}</Text>
            </View>
          ))
        ) : (
          <Text className="empty">暂时没有时间节点</Text>
        )}
      </View>
      <View className="section">
        <Text className="section-title">人物与关系</Text>
        {entities.length ? (
          entities.map((item) => (
            <View className="list-card" key={item.id}>
              <Text className="list-title">{item.name}</Text>
              <Text className="list-meta">
                {item.relationship ||
                  (
                    {
                      person: "人物",
                      place: "地点",
                      organization: "机构",
                    } as Record<string, string>
                  )[item.entity_type] ||
                  item.entity_type}
              </Text>
            </View>
          ))
        ) : (
          <Text className="empty">暂时没有人物与关系记录</Text>
        )}
      </View>
      <View className="section">
        <Text className="section-title" id="guide-memory-facts">
          事实记忆
        </Text>
        {!claims.length && <Text className="empty">暂时没有事实记录</Text>}
        {claims.slice(0, 20).map((item) => (
          <View className="list-card" key={item.id}>
            <Text className="list-meta">{item.claim_text}</Text>
            <Text className="hint">来源：{item.source_quote || "未标注"}</Text>
          </View>
        ))}
      </View>
      <View className="section">
        <Text className="section-title" id="guide-memory-conflicts">
          待核对记录
        </Text>
        {conflicts.length ? (
          conflicts.map((item) => (
            <View className="list-card" key={item.id}>
              <Text className="list-title">
                {item.status === "open"
                  ? "待核对"
                  : item.status === "resolved"
                    ? "已核对"
                    : "记录核对"}
              </Text>
              <Text className="list-meta">{item.description}</Text>
            </View>
          ))
        ) : (
          <Text className="empty">当前没有待处理冲突</Text>
        )}
      </View>
    </PageFrame>
  );
}
