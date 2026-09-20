import { LoaderCircle, Mic, MicOff, Phone, PhoneOff } from "lucide-react";
import { useEffect, useRef } from "react";
import type { useRealtimeInterview } from "../hooks/useRealtimeInterview";
import { Button } from "./ui/button";

export function InterviewVoice({
  voice,
  disabled,
}: {
  voice: ReturnType<typeof useRealtimeInterview>;
  disabled: boolean;
}) {
  const transcript = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  useEffect(() => {
    if (transcript.current && followLatest.current) {
      transcript.current.scrollTop = transcript.current.scrollHeight;
    }
  }, [voice.messages, voice.draft]);
  const time = `${Math.floor(voice.seconds / 60)
    .toString()
    .padStart(2, "0")}:${(voice.seconds % 60).toString().padStart(2, "0")}`;
  const label =
    voice.phase === "connecting"
      ? "正在连接"
      : voice.phase === "ending"
        ? "正在结束"
        : voice.muted
          ? "麦克风已静音"
          : voice.phase === "speaking"
            ? "AI 正在说话"
            : "正在倾听";
  return (
    <div className={`interview-voice ${voice.active ? "is-active" : ""}`}>
      <div className="voice-toolbar">
        {!voice.active ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled || voice.busy || !voice.enabled}
            title={
              !voice.enabled
                ? "实时语音暂未开通"
                : voice.remoteActive
                  ? "另一窗口正在通话"
                  : "开始语音采访"
            }
            onClick={() => void voice.start()}
          >
            <Phone size={16} /> 开始语音采访
          </Button>
        ) : (
          <>
            <span className="voice-status" role="status">
              {voice.phase === "connecting" || voice.phase === "ending" ? (
                <LoaderCircle size={16} className="composer-spinner" />
              ) : (
                <span className="voice-live-dot" />
              )}
              {label} <time>{time}</time>
            </span>
            <div className="voice-buttons">
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label={voice.muted ? "取消静音" : "静音"}
                title={voice.muted ? "取消静音" : "静音"}
                aria-pressed={voice.muted}
                disabled={
                  voice.phase === "connecting" || voice.phase === "ending"
                }
                onClick={voice.toggleMute}
              >
                {voice.muted ? <MicOff size={18} /> : <Mic size={18} />}
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="icon"
                title="结束语音采访"
                aria-label="结束语音采访"
                disabled={voice.phase === "ending"}
                onClick={voice.end}
              >
                <PhoneOff size={18} />
              </Button>
            </div>
          </>
        )}
        {voice.updateStatus && (
          <small role="status">{voice.updateStatus}</small>
        )}
        {!voice.active && voice.remoteActive && (
          <small role="status">语音采访正在进行</small>
        )}
      </div>
      {(voice.messages.length > 0 || voice.draft) && (
        <div
          className="voice-transcript"
          aria-label="语音通话转写"
          ref={transcript}
          onScroll={(event) => {
            const element = event.currentTarget;
            followLatest.current =
              element.scrollHeight - element.scrollTop - element.clientHeight <
              60;
          }}
        >
          {voice.messages.map((item) => (
            <p key={`${item.role}:${item.id}`} className={item.role}>
              <span>{item.role === "user" ? "我" : "采访 AI"}</span>
              {item.text}
            </p>
          ))}
          {voice.draft && (
            <p className={`${voice.draft.role} pending`}>
              <span>{voice.draft.role === "user" ? "我" : "采访 AI"}</span>
              {voice.draft.text}
            </p>
          )}
        </div>
      )}
      {voice.error && (
        <p className="form-error" role="alert">
          {voice.error}
        </p>
      )}
    </div>
  );
}
