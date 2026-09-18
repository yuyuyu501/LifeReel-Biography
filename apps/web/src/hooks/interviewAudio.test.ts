import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { describe, expect, it, vi } from "vitest";
import { InterviewAudio } from "./interviewAudio";

describe("microphone conversion", () => {
  it.each([16000, 44100, 48000])(
    "preserves duration and PCM16 frames at %i Hz",
    (rate) => {
      const frames: ArrayBuffer[] = [];
      let Processor: new () => { process: (inputs: Float32Array[][]) => void };
      runInNewContext(
        readFileSync(
          resolve(
            dirname(fileURLToPath(import.meta.url)),
            "../../public/audio/interview-capture.js",
          ),
          "utf8",
        ),
        {
          sampleRate: rate,
          AudioWorkletProcessor: class {
            port = {
              postMessage: (buffer: ArrayBuffer) => frames.push(buffer),
            };
          },
          registerProcessor: (_name: string, value: typeof Processor) => {
            Processor = value;
          },
        },
      );
      const processor = new Processor!();
      const source = new Float32Array(rate).fill(0.5);
      for (let index = 0; index < source.length; index += 128)
        processor.process([[source.slice(index, index + 128)]]);
      expect(frames).toHaveLength(50);
      expect(frames.every((frame) => frame.byteLength === 640)).toBe(true);
      expect(new DataView(frames[0]).getInt16(0, true)).toBe(16384);
    },
  );
});

it("releases a microphone permission request that completes after navigation", async () => {
  let release: (stream: MediaStream) => void = () => undefined;
  const stop = vi.fn();
  const close = vi.fn();
  vi.stubGlobal(
    "AudioContext",
    class {
      state = "running";
      resume = async () => undefined;
      close = close;
    },
  );
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: () =>
        new Promise<MediaStream>((resolve) => {
          release = resolve;
        }),
    },
  });
  const audio = new InterviewAudio();
  const opening = audio.open(vi.fn());
  await Promise.resolve();
  audio.close();
  release({ getTracks: () => [{ stop }] } as unknown as MediaStream);
  await opening;
  expect(stop).toHaveBeenCalledOnce();
  expect(close).toHaveBeenCalledOnce();
  vi.unstubAllGlobals();
});

it("stops all scheduled playback immediately on interruption", async () => {
  const sources: {
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
  }[] = [];
  const disconnect = vi.fn();
  const trackStop = vi.fn();
  vi.stubGlobal(
    "AudioContext",
    class {
      state = "running";
      currentTime = 1;
      destination = {};
      resume = async () => undefined;
      close = vi.fn();
      audioWorklet = { addModule: async () => undefined };
      createBuffer = (_channels: number, length: number, rate: number) => ({
        getChannelData: () => new Float32Array(length),
        duration: length / rate,
      });
      createBufferSource = () => {
        const source = {
          start: vi.fn(),
          stop: vi.fn(),
          disconnect,
          connect: vi.fn(),
        };
        sources.push(source);
        return source;
      };
      createGain = () => ({ gain: { value: 1 }, connect: vi.fn(), disconnect });
      createMediaStreamSource = () => ({
        connect: (node: unknown) => node,
        disconnect,
      });
    },
  );
  vi.stubGlobal(
    "AudioWorkletNode",
    class {
      port = {};
      disconnect = disconnect;
      connect = (node: unknown) => node;
    },
  );
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: async () => ({ getTracks: () => [{ stop: trackStop }] }),
    },
  });
  const audio = new InterviewAudio();
  await audio.open(vi.fn());
  audio.play(btoa("\x00\x00\x00\x40"));
  audio.play(btoa("\x00\x00\x00\x40"));
  expect(audio.isPlaying).toBe(true);
  audio.interrupt();
  expect(sources.every((source) => source.stop.mock.calls.length === 1)).toBe(
    true,
  );
  expect(audio.isPlaying).toBe(false);
  audio.close();
  expect(trackStop).toHaveBeenCalledOnce();
  vi.unstubAllGlobals();
});
