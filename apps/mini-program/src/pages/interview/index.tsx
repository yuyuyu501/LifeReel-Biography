import { useEffect, useRef, useState } from "react";
import { Button, Text, Textarea, View } from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type { InterviewWorkspace } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { newRequestId } from "../../shared/uuid";
import { PreviewNotice } from "../../shared/PreviewNotice";

export default function InterviewPage() {
  const subjectId = getCurrentInstance().router?.params.subjectId || "";
  const [workspace, setWorkspace] = useState<InterviewWorkspace | null>(null);
  const [answer, setAnswer] = useState("");
  const [assetId, setAssetId] = useState<string | undefined>();
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const recorder = useRef<Taro.RecorderManager | null>(null);
  const running = ["queued", "running"].includes(
    workspace?.latest_workflow?.status || "",
  );
  useEffect(() => {
    if (!subjectId) {
      setError("请从人物首页进入采访");
      return;
    }
    let active = true;
    miniApi
      .startInterview({ subject_id: subjectId })
      .then((s) => miniApi.workspace(s.id))
      .then((value) => {
        if (active) setWorkspace(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [subjectId]);
  useEffect(() => {
    if (!running || !workspace) return;
    const timer = setInterval(() => {
      miniApi
        .workspace(workspace.session.id)
        .then(setWorkspace)
        .catch((e) => setError(e.message));
    }, 2000);
    return () => clearInterval(timer);
  }, [running, workspace?.session.id]);
  function startRecording() {
    if (process.env.TARO_ENV === "h5") {
      setError("浏览器预览不录音，请在开发者工具或真机验证");
      return;
    }
    const first = !recorder.current;
    recorder.current ??= Taro.getRecorderManager();
    const manager = recorder.current;
    const finished = async (
      result: Taro.RecorderManager.OnStopCallbackResult,
    ) => {
      setRecording(false);
      setBusy(true);
      try {
        const asset = await miniApi.uploadAsset(
          result.tempFilePath,
          subjectId,
          "audio",
          workspace?.session.id,
        );
        setAssetId(asset.id);
      } catch (e) {
        setError(e instanceof Error ? e.message : "录音上传失败");
      } finally {
        setBusy(false);
      }
    };
    if (first) manager.onStop(finished);
    manager.start({ duration: 600000, format: "mp3" });
    setRecording(true);
  }
  async function submit() {
    if (!workspace || (!answer.trim() && !assetId)) return;
    setBusy(true);
    setError("");
    try {
      const current =
        workspace.session.rounds[workspace.session.rounds.length - 1];
      await miniApi.createTurn(workspace.session.id, {
        round_id: current && !current.answer_text ? current.id : undefined,
        answer_text: answer.trim() || undefined,
        asset_ids: assetId ? [assetId] : [],
        idempotency_key: newRequestId(),
      });
      setAnswer("");
      setAssetId(undefined);
      setWorkspace(await miniApi.workspace(workspace.session.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "提交失败，内容仍保留");
    } finally {
      setBusy(false);
    }
  }
  return (
    <View className="page">
      <PreviewNotice />
      <Text className="title">人生采访</Text>
      <Text className="hint">
        可以自由讲述，AI
        会补问并整理同一份人生资料。发现错误，直接说明正确内容。
      </Text>
      {error && <Text className="error">{error}</Text>}
      {workspace ? (
        <>
          <View className="action-row">
            <Button
              onClick={() =>
                Taro.navigateTo({
                  url: `/pages/profile/index?subjectId=${subjectId}`,
                })
              }
            >
              查看与编辑资料表
            </Button>
            <Button
              onClick={() =>
                Taro.navigateTo({
                  url: `/pages/books/index?subjectId=${subjectId}`,
                })
              }
            >
              前往写书
            </Button>
          </View>
          {workspace.profile && (
            <View className="status-box">
              <Text>{workspace.profile.readiness.message}</Text>
              <Text>
                {workspace.profile.readiness.processed_fields} / 67
                项已处理，不要求全部填完。
              </Text>
            </View>
          )}
          {workspace.session.rounds.map((round) => (
            <View className="card" key={round.id}>
              {round.question_text && (
                <Text className="question">{round.question_text}</Text>
              )}
              {round.answer_text && (
                <Text className="list-meta">{round.answer_text}</Text>
              )}
            </View>
          ))}
          <View className="card">
            <Textarea
              className="textarea"
              value={answer}
              maxlength={16000}
              placeholder="继续讲述或更正资料"
              onInput={(e) => setAnswer(e.detail.value)}
            />
            <View className="action-row">
              <Button
                disabled={busy || running}
                onClick={
                  recording ? () => recorder.current?.stop() : startRecording
                }
              >
                {recording ? "停止录音" : "录一段普通语音"}
              </Button>
              <Button
                disabled={
                  busy || running || recording || (!answer.trim() && !assetId)
                }
                onClick={submit}
              >
                {running ? "正在整理资料……" : "发送讲述"}
              </Button>
            </View>
            {assetId && (
              <Text className="hint">录音已上传，可直接提交整理</Text>
            )}
            {workspace.latest_workflow?.status === "failed" && (
              <Text className="error">
                整理失败，原回答已保存，请稍后重试或直接编辑资料表。
              </Text>
            )}
          </View>
        </>
      ) : (
        <Text className="hint">正在读取采访资料……</Text>
      )}
    </View>
  );
}
