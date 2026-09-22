import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { useRealtimeInterview } from "./useRealtimeInterview";

const audio = vi.hoisted(() => ({
  open: vi.fn(),
  close: vi.fn(),
  play: vi.fn(),
  interrupt: vi.fn(),
  stopMicrophone: vi.fn(),
  mute: vi.fn(),
  muted: false,
  isPlaying: false,
}));
vi.mock("./interviewAudio", () => ({
  InterviewAudio: class {
    constructor() {
      return audio;
    }
  },
}));

class Socket {
  static OPEN = 1;
  static current: Socket;
  readyState = 1;
  bufferedAmount = 0;
  onmessage?: (event: { data: string }) => void;
  onclose?: () => void;
  send = vi.fn();
  close = vi.fn();
  constructor() {
    Socket.current = this;
  }
  event(value: object) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
}

const call = {
  id: "call-1",
  session_id: "session-1",
  status: "completed",
  messages: [],
  source_asset_id: null,
  workflow_id: null,
  error_code: null,
  started_at: "",
  ended_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  audio.open.mockResolvedValue(undefined);
  vi.spyOn(api, "interviewVoiceState").mockResolvedValue({
    enabled: true,
    max_seconds: 900,
    call: null,
  });
  vi.spyOn(api, "startInterviewVoice").mockResolvedValue(call);
  vi.stubGlobal("WebSocket", Socket);
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(() => useRealtimeInterview("session-1"), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

it("handles interruption, mute, transcript roles and graceful end", async () => {
  const { result } = setup();
  await waitFor(() => expect(result.current.enabled).toBe(true));
  await act(async () => {
    await result.current.start();
  });
  const socket = Socket.current;
  act(() => socket.event({ type: "ready" }));
  expect(result.current.active).toBe(true);
  act(() => socket.event({ type: "audio", audio: "AAAA" }));
  expect(audio.play).toHaveBeenCalledOnce();
  act(() => socket.event({ type: "interrupted" }));
  act(() => socket.event({ type: "audio", audio: "AAAA" }));
  expect(audio.interrupt).toHaveBeenCalledOnce();
  expect(audio.play).toHaveBeenCalledOnce();
  act(() => socket.event({ type: "audio.started" }));
  act(() => socket.event({ type: "audio", audio: "AAAA" }));
  expect(audio.play).toHaveBeenCalledTimes(2);
  act(() => result.current.toggleMute());
  expect(socket.send).toHaveBeenCalledWith(
    JSON.stringify({ type: "mute", muted: true }),
  );
  act(() =>
    socket.event({
      type: "transcript.done",
      id: "1",
      role: "user",
      text: "小时候住在村里",
    }),
  );
  act(() =>
    socket.event({
      type: "transcript.done",
      id: "1",
      role: "assistant",
      text: "村里有哪些亲人？",
    }),
  );
  expect(result.current.messages).toHaveLength(2);
  act(() => socket.event({ type: "update.started" }));
  expect(result.current.updateStatus).toContain("正在更新");
  act(() => socket.event({ type: "update.done", memory_updated: true, script_updated: true }));
  expect(result.current.updateStatus).toBe("知识和剧本已更新");
  act(() => socket.event({ type: "update.done", memory_updated: true,
    script_updated: false, pending: true }));
  expect(result.current.updateStatus).toBe("正在处理后续讲述…");
  expect(result.current.active).toBe(true);
  act(() => result.current.end());
  expect(audio.stopMicrophone).toHaveBeenCalledOnce();
  expect(result.current.phase).toBe("ending");
  act(() => socket.event({ type: "audio.started" }));
  act(() => socket.event({ type: "audio", audio: "AAAA" }));
  expect(audio.play).toHaveBeenCalledTimes(2);
  act(() =>
    socket.event({
      type: "ended",
      call,
    }),
  );
  expect(result.current.messages).toEqual([]);
  expect(result.current.active).toBe(false);
  expect(audio.close).toHaveBeenCalledOnce();
});

it("does not start a paid session when microphone permission is denied", async () => {
  audio.open.mockRejectedValue(new DOMException("Denied", "NotAllowedError"));
  const { result } = setup();
  await act(async () => {
    await result.current.start();
  });
  expect(api.startInterviewVoice).not.toHaveBeenCalled();
  expect(result.current.error).toContain("麦克风权限");
  expect(audio.close).toHaveBeenCalledOnce();
});

it("closes tracks and socket on navigation without reconnecting", async () => {
  const { result, unmount } = setup();
  await act(async () => {
    await result.current.start();
  });
  const socket = Socket.current;
  act(() => socket.event({ type: "ready" }));
  unmount();
  expect(socket.close).toHaveBeenCalledOnce();
  expect(audio.close).toHaveBeenCalledOnce();
  expect(api.startInterviewVoice).toHaveBeenCalledOnce();
});

it("refreshes the workspace while still talking and clears temporary captions on disconnect", async () => {
  const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
  const { result } = setup();
  await act(async () => { await result.current.start(); });
  const socket = Socket.current;
  act(() => socket.event({ type: "ready" }));
  act(() => socket.event({ type: "transcript.done", id: "one", role: "user", text: "临时字幕" }));
  act(() => socket.event({ type: "update.done", memory_updated: true, script_updated: true }));
  expect(result.current.active).toBe(true);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["interview-workspace", "session-1"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["memory-graph"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["scripts"] });
  act(() => socket.onclose?.());
  expect(result.current.messages).toEqual([]);
  expect(result.current.draft).toBeNull();
});
