import { useEffect, useState } from "react";
import { Button, Text, View } from "@tarojs/components";
import type { ProductionRun, ScriptProject } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";

export default function ProductionPage() {
  const [runs, setRuns] = useState<ProductionRun[]>([]);
  const [projects, setProjects] = useState<ScriptProject[]>([]);
  const [selectedProject, setSelectedProject] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = () =>
    Promise.all([miniApi.productionRuns(), miniApi.scripts()]).then(
      ([items, scripts]) => {
        setRuns(items);
        setProjects(scripts);
        setSelectedProject(scripts[0]?.id || "");
      },
    );
  useEffect(() => {
    load().catch((reason) =>
      setError(reason instanceof Error ? reason.message : "任务加载失败"),
    );
  }, []);

  const start = async () => {
    if (!selectedProject) return;
    setLoading(true);
    setError("");
    try {
      const run = await miniApi.startProduction({
        project_id: selectedProject,
      });
      setRuns((items) => [run, ...items]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "视频任务创建失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <View className="page">
      <Text className="eyebrow">PRODUCTION</Text>
      <Text className="title">视频任务</Text>
      {error ? <Text className="error">{error}</Text> : null}
      <View className="card">
        <Text className="label">选择剧本</Text>
        {projects.map((project) => (
          <View
            className={`select-row ${selectedProject === project.id ? "selected" : ""}`}
            key={project.id}
            onClick={() => setSelectedProject(project.id)}
          >
            <Text>
              {project.title} · v{project.version_number}
            </Text>
          </View>
        ))}
        <Button
          className="primary-button"
          loading={loading}
          disabled={loading || !selectedProject}
          onClick={start}
        >
          创建视频任务
        </Button>
        <Text className="hint">
          任务由服务器异步处理，页面关闭后可在这里继续查看。
        </Text>
      </View>
      <View className="section">
        <Text className="section-title">历史任务</Text>
        {runs.length ? (
          runs.map((run) => (
            <View className="list-card" key={run.id}>
              <Text className="list-title">{run.status}</Text>
              <Text className="list-meta">
                {run.provider} · {new Date(run.created_at).toLocaleString()}
              </Text>
              {run.error_message ? (
                <Text className="error">{run.error_message}</Text>
              ) : null}
              {run.output_manifest?.segments ? (
                <Text className="hint">
                  已完成片段：
                  {
                    run.output_manifest.segments.filter(
                      (segment) => segment.status === "completed",
                    ).length
                  }
                </Text>
              ) : null}
            </View>
          ))
        ) : (
          <Text className="empty">还没有视频任务</Text>
        )}
      </View>
    </View>
  );
}
