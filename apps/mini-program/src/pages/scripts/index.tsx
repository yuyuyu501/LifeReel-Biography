import { useEffect, useState } from "react";
import { Button, Text, View } from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type { ScriptProject } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";

export default function ScriptsPage() {
  const subjectId = getCurrentInstance().router?.params?.subjectId || "";
  const [projects, setProjects] = useState<ScriptProject[]>([]);
  const [selected, setSelected] = useState<ScriptProject | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = () =>
    miniApi.scripts().then((items) => {
      setProjects(items);
      setSelected(
        items.find((item) => item.subject_id === subjectId) || items[0] || null,
      );
    });

  useEffect(() => {
    load().catch((reason) =>
      setError(reason instanceof Error ? reason.message : "剧本加载失败"),
    );
  }, []);

  const generate = async () => {
    if (!subjectId) return;
    setLoading(true);
    setError("");
    try {
      const project = await miniApi.generateScript({ subject_id: subjectId });
      setSelected(project);
      setProjects((items) => [
        project,
        ...items.filter((item) => item.id !== project.id),
      ]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "剧本生成失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <View className="page">
      <Text className="eyebrow">SCRIPT STUDIO</Text>
      <Text className="title">剧本与分镜</Text>
      {error ? <Text className="error">{error}</Text> : null}
      <Button
        className="primary-button"
        loading={loading}
        disabled={loading || !subjectId}
        onClick={generate}
      >
        生成或更新剧本
      </Button>
      <View className="section">
        <Text className="section-title">历史版本</Text>
        {projects.map((item) => (
          <View
            className="list-card"
            key={item.id}
            onClick={() => setSelected(item)}
          >
            <Text className="list-title">{item.title}</Text>
            <Text className="list-meta">
              版本 {item.version_number} · {item.status}
            </Text>
          </View>
        ))}
      </View>
      {selected ? (
        <View className="section">
          <Text className="section-title">{selected.title} · 分镜</Text>
          {selected.scenes.map((scene) => (
            <View className="card scene-card" key={scene.id}>
              <Text className="list-title">
                {scene.order_index}. {scene.heading}
              </Text>
              <Text className="list-meta">{scene.plot || scene.narration}</Text>
              <Text className="hint">视觉：{scene.visual_prompt}</Text>
              {scene.visual_constraints ? (
                <Text className="constraint">
                  人脸策略：{scene.visual_constraints.face_policy}；禁止：
                  {scene.visual_constraints.forbidden_elements.join("、") ||
                    "无"}
                </Text>
              ) : null}
              {scene.shots?.map((shot) => (
                <View className="shot-card" key={shot.id}>
                  <Text className="list-meta">
                    {shot.order_index}. {shot.shot_type} ·{" "}
                    {shot.duration_seconds} 秒
                  </Text>
                  <Text className="hint">{shot.visual_prompt}</Text>
                </View>
              ))}
            </View>
          ))}
        </View>
      ) : (
        <Text className="empty">还没有剧本，请先生成。</Text>
      )}
      <Button
        className="text-button"
        onClick={() => Taro.navigateTo({ url: "/pages/production/index" })}
      >
        查看视频任务
      </Button>
    </View>
  );
}
