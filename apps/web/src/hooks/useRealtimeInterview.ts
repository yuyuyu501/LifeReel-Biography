import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  API_BASE_URL,
  type InterviewVoiceCall,
  type VoiceMessage,
} from "../api/client";
import { ApiError, errorMessage } from "../api/errors";
import { InterviewAudio } from "./interviewAudio";

type Phase = "idle" | "connecting" | "listening" | "speaking" | "ending";
type VoiceRuntime = {
  audio: InterviewAudio;
  socket?: WebSocket;
  canceled: boolean;
  ready: boolean;
  ended: boolean;
  closing: boolean;
  blockAudio: boolean;
  started: number;
  timer?: ReturnType<typeof setInterval>;
  timeout?: ReturnType<typeof setTimeout>;
};
const activeStatuses = ["connecting", "active", "closing"];

export function useRealtimeInterview(sessionId: string) {
  const queryClient = useQueryClient();
  const state = useQuery({
    queryKey: ["interview-voice", sessionId],
    queryFn: () => api.interviewVoiceState(sessionId),
    enabled: Boolean(sessionId),
    refetchInterval: 5000,
    retry: false,
  });
  const [phase, setPhase] = useState<Phase>("idle");
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<VoiceMessage[]>([]);
  const [draft, setDraft] = useState<VoiceMessage | null>(null);
  const [updateStatus, setUpdateStatus] = useState("");
  const runtime = useRef<VoiceRuntime | null>(null);

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: ["interview-workspace", sessionId],
    });
    void queryClient.invalidateQueries({
      queryKey: ["interview-voice", sessionId],
    });
    void queryClient.invalidateQueries({ queryKey: ["interviews"] });
    for (const key of ["scripts", "memory-overview", "memory-graph", "memory-timeline",
      "memory-conflicts", "persons", "wallet", "wallet-ledger"]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  }, [queryClient, sessionId]);

  const remoteStatus = state.data?.call?.status;
  const remoteCallId = state.data?.call?.id;
  useEffect(() => {
    if (remoteStatus && !activeStatuses.includes(remoteStatus)) refresh();
  }, [remoteStatus, remoteCallId, refresh]);

  function cleanup() {
    const current = runtime.current;
    if (!current) return;
    current.canceled = true;
    clearInterval(current.timer);
    clearTimeout(current.timeout);
    current.audio.close();
    if (current.socket) {
      current.socket.onclose = null;
      current.socket.onmessage = null;
      current.socket.onerror = null;
      current.socket.close();
    }
    runtime.current = null;
    setMessages([]);
    setDraft(null);
  }

  useEffect(
    () => () => {
      const current = runtime.current;
      if (!current) return;
      current.canceled = true;
      clearInterval(current.timer);
      clearTimeout(current.timeout);
      current.audio.close();
      if (current.socket) {
        current.socket.onclose = null;
        current.socket.onmessage = null;
        current.socket.onerror = null;
        current.socket.close();
      }
      runtime.current = null;
    },
    [sessionId],
  );

  async function start() {
    if (runtime.current) return;
    const current: VoiceRuntime = {
      audio: new InterviewAudio(),
      canceled: false,
      ready: false,
      ended: false,
      closing: false,
      blockAudio: false,
      started: Date.now(),
    };
    runtime.current = current;
    setError(null);
    setUpdateStatus("");
    setMessages([]);
    setDraft(null);
    setMuted(false);
    setSeconds(0);
    setPhase("connecting");
    try {
      await current.audio.open((frame) => {
        if (current.ready && current.socket?.readyState === WebSocket.OPEN) {
          if (current.socket.bufferedAmount > 64000) {
            setError("网络传输过慢，通话已中断。已完成的知识和剧本更新仍然保留。");
            cleanup();
            setPhase("idle");
            refresh();
            return;
          }
          current.socket.send(frame);
        }
      });
      if (current.canceled) return;
      const call = await api.startInterviewVoice(sessionId);
      if (current.canceled) return;
      const url = new URL(
        `/v1/interview-voice/${call.id}/stream`,
        API_BASE_URL || location.origin,
      );
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(url);
      current.socket = socket;
      current.timeout = setTimeout(() => {
        if (!current.ready && !current.canceled) {
          setError("语音连接超时，请稍后重试。");
          cleanup();
          setPhase("idle");
          refresh();
        }
      }, 25000);
      socket.onmessage = (message) => {
        if (current.canceled) return;
        try {
          const event = JSON.parse(message.data);
          if (event.type === "ready") {
            current.ready = true;
            current.started = Date.now();
            clearTimeout(current.timeout);
            setPhase("listening");
            current.timer = setInterval(() => {
              setSeconds(Math.floor((Date.now() - current.started) / 1000));
              if (current.ready && !current.audio.isPlaying) {
                setPhase((value) =>
                  value === "speaking" ? "listening" : value,
                );
              }
              if (socket.readyState === WebSocket.OPEN)
                socket.send(JSON.stringify({ type: "ping" }));
            }, 1000);
          } else if (event.type === "interrupted") {
            current.audio.interrupt();
            current.blockAudio = true;
            setPhase((value) => (value === "ending" ? value : "listening"));
          } else if (event.type === "audio.started") {
            current.blockAudio = false;
            setPhase((value) => (value === "ending" ? value : "speaking"));
          } else if (
            event.type === "audio" &&
            !current.blockAudio &&
            !current.closing
          ) {
            current.audio.play(event.audio);
          } else if (event.type === "transcript.delta") {
            setDraft((value) => ({
              id: event.id,
              role: event.role,
              text:
                (value && value.id === event.id && value.role === event.role
                  ? value.text
                  : "") + event.text,
            }));
          } else if (event.type === "transcript.done") {
            setDraft(null);
            setMessages((items) => [
              ...items.filter(
                (item) => !(item.id === event.id && item.role === event.role),
              ).slice(-1),
              { id: event.id, role: event.role, text: event.text },
            ]);
          } else if (event.type === "transcript.failed") {
            setDraft(null);
            setError("刚才一段没有听清，请再说一遍。");
          } else if (event.type === "update.started") {
            setUpdateStatus("正在更新知识和剧本…");
          } else if (event.type === "update.done") {
            setUpdateStatus(event.script_updated ?
              (event.memory_updated ? "知识和剧本已更新" : "剧本已更新") :
              event.memory_updated ? "知识已更新，继续讲述可完善剧本" : "可以继续讲述");
            refresh();
          } else if (event.type === "update.failed") {
            setUpdateStatus("本轮更新未完成");
            setError("本轮知识或剧本更新失败，请稍后重述需要补充的内容。" +
              errorMessage(new ApiError(event.code, 503)));
            refresh();
          } else if (event.type === "limit") {
            setError(errorMessage(new ApiError("VOICE_LIMIT_REACHED", 409)));
            current.ready = false;
            current.closing = true;
            current.audio.stopMicrophone();
            setPhase("ending");
          } else if (event.type === "error") {
            setError(errorMessage(new ApiError(event.code, 503)));
          } else if (event.type === "ended") {
            const result = event.call as InterviewVoiceCall;
            current.ended = true;
            setDraft(null);
            setMessages([]);
            if (result.error_code)
              setError(errorMessage(new ApiError(result.error_code, 503)));
            cleanup();
            setPhase("idle");
            refresh();
          }
        } catch {
          setError("语音数据异常，已停止通话。");
          cleanup();
          setPhase("idle");
          refresh();
        }
      };
      socket.onerror = () => {
        setError("语音连接失败，请检查网络后重试。");
      };
      socket.onclose = () => {
        if (current.canceled) return;
        if (!current.ended)
          setError("语音连接已断开。已完成的知识和剧本更新仍然保留。");
        cleanup();
        setPhase("idle");
        setDraft(null);
        refresh();
      };
    } catch (failure) {
      if (current.canceled) return;
      const name =
        failure instanceof Error || failure instanceof DOMException
          ? failure.name
          : "";
      setError(
        name === "NotAllowedError"
          ? "麦克风权限未开启，请允许浏览器使用麦克风。"
          : failure instanceof ApiError
            ? errorMessage(failure)
            : failure instanceof Error
              ? failure.message
              : "无法开始语音采访。",
      );
      cleanup();
      setPhase("idle");
      refresh();
    }
  }

  function end() {
    const current = runtime.current;
    if (!current) return;
    current.ready = false;
    current.closing = true;
    current.audio.stopMicrophone();
    current.audio.interrupt();
    if (current.socket?.readyState === WebSocket.OPEN) {
      setPhase("ending");
      current.socket.send(JSON.stringify({ type: "end" }));
      clearTimeout(current.timeout);
      current.timeout = setTimeout(() => {
        setUpdateStatus("通话已结束，正在完成最后的知识和剧本更新…");
        cleanup();
        setPhase("idle");
        refresh();
      }, 20000);
    } else {
      cleanup();
      setPhase("idle");
      refresh();
    }
  }

  function toggleMute() {
    const current = runtime.current;
    if (!current?.ready) return;
    const value = !current.audio.muted;
    current.audio.mute(value);
    current.socket?.send(JSON.stringify({ type: "mute", muted: value }));
    setMuted(value);
  }

  const active = phase !== "idle";
  const remoteActive = Boolean(
    state.data?.call && activeStatuses.includes(state.data.call.status),
  );
  return {
    start,
    end,
    toggleMute,
    phase,
    active,
    busy: active || remoteActive,
    muted,
    seconds,
    error,
    messages,
    draft,
    updateStatus,
    enabled: state.data?.enabled ?? false,
    remoteActive,
    maxSeconds: state.data?.max_seconds ?? 900,
  };
}
