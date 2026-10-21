import { useEffect, useRef, useState } from "react";
import { Button, Image, Text, Textarea, View } from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type { InterviewWorkspace } from "@lifereel/contracts";
import { miniApi } from "../../shared/api";
import { newRequestId } from "../../shared/uuid";
import { PageFrame } from "../../shared/PageFrame";
import { Icon } from "../../shared/Icon";

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
    if (first) {
      manager.onStop(finished);
      manager.onError(() => {
        setRecording(false);
        setBusy(false);
        setError("录音失败，请检查麦克风权限后重试");
      });
    }
    try {
      manager.start({ duration: 600000, format: "mp3" });
      setRecording(true);
    } catch {
      setRecording(false);
      setError("录音未能开始，请检查麦克风权限后重试");
    }
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
    <PageFrame
      title="人生采访"
      subtitle="慢慢说，那些值得留下的事。"
      active="interview"
      subjectId={subjectId}
      locked={busy || recording || !!answer.trim() || !!assetId}
      tutorial={{
        ready: !!workspace && !running,
        steps: [
          {
            target: "#guide-interview-answer",
            title: "先讲一段真实经历",
            description:
              "在这里输入故事，也可以直接指出上一条记录哪里不对。不必一次讲完一生。",
          },
          {
            target: "#guide-interview-record",
            title: "也可以用语音讲述",
            description:
              "点这里开始录音，讲完再点结束。首次录音需要允许麦克风权限。",
          },
          {
            target: "#guide-interview-send",
            title: "讲完后，点发送",
            description:
              "发送文字或已上传的录音后，等待助手整理并追问，再继续下一段讲述。",
          },
          {
            target: "#guide-interview-profile",
            title: "最后核对人生资料",
            description:
              "从这里查看整理结果。遗漏可以补充，错误可以更正，确认后再去写书。",
          },
        ],
      }}
    >
      {error && <Text className="error">{error}</Text>}
      {workspace ? (
        <>
          <View className="context-row">
            <Text className="caption">
              {workspace.session.rounds.filter((r) => r.answer_text).length}{" "}
              次讲述已保存
            </Text>
            <Button
              id="guide-interview-profile"
              className="text-button"
              disabled={recording || busy || !!answer.trim() || !!assetId}
              onClick={() =>
                Taro.navigateTo({
                  url: `/pages/profile/index?subjectId=${subjectId}`,
                })
              }
            >
              <Icon name="profile" />
              人生资料
              <Icon name="arrow" />
            </Button>
          </View>
          {workspace.profile && (
            <View className="section">
              <Text className="caption">
                人生资料 · {workspace.profile.readiness.processed_fields} / 67
                项已处理
              </Text>
              <View className="progress-track">
                <View
                  className="progress-fill"
                  style={{
                    width: `${Math.min(100, (workspace.profile.readiness.processed_fields / 67) * 100)}%`,
                  }}
                />
              </View>
            </View>
          )}
          <View className="conversation">
            {!workspace.session.rounds.length && (
              <View className="conversation-empty">
                <Image
                  src={require("../../assets/interview.png")}
                  className="empty-illustration"
                  mode="aspectFit"
                />
                <Text className="hint">还没有保存的讲述</Text>
              </View>
            )}
            {workspace.session.rounds.map((round) => (
              <View key={round.id}>
                {round.question_text && (
                  <View className="message">
                    <View className="message-author">
                      <Icon name="mic" />
                      采访助手
                    </View>
                    <Text className="question">{round.question_text}</Text>
                  </View>
                )}
                {round.answer_text && (
                  <View className="message answer-message">
                    <View className="message-author">我的讲述</View>
                    <Text className="question">{round.answer_text}</Text>
                  </View>
                )}
              </View>
            ))}
            {workspace.latest_workflow?.next_question &&
              workspace.latest_workflow.status === "completed" &&
              !workspace.session.rounds.some(
                (r) =>
                  r.question_text ===
                    workspace.latest_workflow?.next_question && !r.answer_text,
              ) && (
                <View className="message">
                  <View className="message-author">
                    <Icon name="mic" />
                    采访助手
                  </View>
                  <Text className="question">
                    {workspace.latest_workflow.next_question}
                  </Text>
                </View>
              )}
          </View>
          {running && <View className="status-box">正在整理这次讲述……</View>}
          <View className="composer">
            <Textarea
              id="guide-interview-answer"
              className="textarea"
              value={answer}
              maxlength={16000}
              placeholder="继续讲述或更正资料"
              onInput={(e) => setAnswer(e.detail.value)}
              disabled={busy || recording}
            />
            <View className="action-row">
              <Button
                id="guide-interview-record"
                className="record-button"
                disabled={busy || running}
                onClick={
                  recording ? () => recorder.current?.stop() : startRecording
                }
              >
                <Icon name={recording ? "stop" : "mic"} />
                {recording ? "结束录音" : "语音讲述"}
              </Button>
              <Button
                id="guide-interview-send"
                className="primary-button send-button"
                loading={busy}
                disabled={
                  busy || running || recording || (!answer.trim() && !assetId)
                }
                onClick={submit}
              >
                <Icon name="send" tone="white" />
                发送
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
    </PageFrame>
  );
}
