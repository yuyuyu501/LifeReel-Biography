import { useEffect, useRef, useState } from "react";
import { Button, Text, Textarea, View } from "@tarojs/components";
import Taro, { getCurrentInstance } from "@tarojs/taro";
import type {
  InterviewSession,
  InterviewTurnWorkflow,
} from "@lifereel/contracts";
import { miniApi } from "../../shared/api";

export default function InterviewPage() {
  const params = getCurrentInstance().router?.params || {};
  const subjectId = params.subjectId || "";
  const chapterId = params.chapterId || undefined;
  const [session, setSession] = useState<InterviewSession | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [assetId, setAssetId] = useState<string | undefined>();
  const [workflow, setWorkflow] = useState<InterviewTurnWorkflow | null>(null);
  const [recording, setRecording] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const recorder = useRef(Taro.getRecorderManager());

  useEffect(() => {
    if (!subjectId) {
      setError("缺少人物信息，请从首页进入采访");
      setLoading(false);
      return;
    }
    miniApi
      .interviews()
      .then(
        (items) =>
          items.find(
            (item) =>
              item.subject_id === subjectId &&
              item.status === "active" &&
              (!chapterId || item.chapter_id === chapterId),
          ) ||
          miniApi.startInterview({
            subject_id: subjectId,
            chapter_id: chapterId,
          }),
      )
      .then(async (value) => {
        setSession(value);
        const next = await miniApi.nextQuestion(value.id);
        setQuestion(next.question_text);
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "采访初始化失败"),
      )
      .finally(() => setLoading(false));
  }, [subjectId, chapterId]);

  const startRecording = () => {
    recorder.current.start({ duration: 600000, format: "mp3" });
    setRecording(true);
    recorder.current.onStop(async (result) => {
      setRecording(false);
      try {
        const asset = await miniApi.uploadAsset(
          result.tempFilePath,
          subjectId,
          "audio",
          session?.id,
        );
        setAssetId(asset.id);
        Taro.showToast({ title: "录音已上传", icon: "success" });
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "录音上传失败");
      }
    });
  };

  const stopRecording = () => recorder.current.stop();

  const submit = async () => {
    if (!session || !question || !answer.trim()) return;
    setLoading(true);
    setError("");
    try {
      const round = await miniApi.createRound(session.id, {
        question_text: question,
        question_source: "mini_program",
      });
      await miniApi.answerRound(session.id, round.id, {
        answer_text: answer.trim(),
        ...(assetId ? { source_asset_id: assetId } : {}),
      });
      const created = await miniApi.createTurn(session.id, {
        round_id: round.id,
        answer_text: answer.trim(),
        ...(assetId ? { asset_ids: [assetId] } : {}),
        idempotency_key: `mini-${session.id}-${round.id}`,
      });
      setWorkflow(created);
      setAnswer("");
      setAssetId(undefined);
      const next = await miniApi.nextQuestion(session.id);
      setQuestion(next.question_text);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "回答提交失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <View className="page">
      <Text className="eyebrow">INTERVIEW</Text>
      <Text className="title">把记忆说清楚</Text>
      {loading && !session ? <Text className="hint">正在准备采访…</Text> : null}
      {error ? <Text className="error">{error}</Text> : null}
      {session ? (
        <View className="card">
          <Text className="section-title">
            第 {session.round_count + 1} 个问题
          </Text>
          <Text className="question">{question || "正在生成问题…"}</Text>
          <Textarea
            className="textarea"
            value={answer}
            maxlength={16000}
            placeholder="写下真实、具体的回答"
            onInput={(event) => setAnswer(event.detail.value)}
          />
          <View className="action-row">
            <Button
              className="secondary-button"
              onClick={recording ? stopRecording : startRecording}
            >
              {recording ? "停止录音" : "录一段普通语音"}
            </Button>
            <Button
              className="primary-button"
              disabled={loading || !answer.trim()}
              onClick={submit}
            >
              提交回答
            </Button>
          </View>
          {assetId ? <Text className="hint">录音已附加到这次回答</Text> : null}
          {workflow ? (
            <View className="status-box">
              <Text>处理状态：{workflow.status}</Text>
              <Text>{workflow.next_question || "知识和剧本正在更新"}</Text>
            </View>
          ) : null}
        </View>
      ) : null}
      <Button className="text-button" onClick={() => Taro.navigateBack()}>
        返回
      </Button>
    </View>
  );
}
