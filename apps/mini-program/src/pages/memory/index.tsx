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
    <View className="page">
      <Text className="eyebrow">MEMORY GRAPH</Text>
      <Text className="title">记忆与时间线</Text>
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
        <Text className="section-title">时间线</Text>
        {timeline.length ? (
          timeline.map((item) => (
            <View className="list-card" key={item.id}>
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
                {item.entity_type} · {item.relationship}
              </Text>
            </View>
          ))
        ) : (
          <Text className="empty">暂时没有实体</Text>
        )}
      </View>
      <View className="section">
        <Text className="section-title">事实记忆</Text>
        {claims.slice(0, 20).map((item) => (
          <View className="list-card" key={item.id}>
            <Text className="list-meta">{item.claim_text}</Text>
            <Text className="hint">来源：{item.source_quote || "未标注"}</Text>
          </View>
        ))}
      </View>
      <View className="section">
        <Text className="section-title">冲突</Text>
        {conflicts.length ? (
          conflicts.map((item) => (
            <View className="list-card" key={item.id}>
              <Text className="list-title">{item.status}</Text>
              <Text className="list-meta">{item.description}</Text>
            </View>
          ))
        ) : (
          <Text className="empty">当前没有待处理冲突</Text>
        )}
      </View>
    </View>
  );
}
