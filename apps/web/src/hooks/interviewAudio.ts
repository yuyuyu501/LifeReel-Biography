export class InterviewAudio {
  private stream?: MediaStream;
  private context?: AudioContext;
  private capture?: AudioWorkletNode;
  private input?: MediaStreamAudioSourceNode;
  private silent?: GainNode;
  private sources = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private disposed = false;
  muted = false;

  get isPlaying() {
    return this.sources.size > 0;
  }

  async open(onAudio: (frame: ArrayBuffer) => void) {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
      throw new Error(
        "当前浏览器无法使用实时语音，请通过 HTTPS 打开并使用新版浏览器。",
      );
    }
    // Create/resume during the user's click to unlock playback on mobile browsers.
    const context = new AudioContext({ sampleRate: 16000 });
    this.context = context;
    await context.resume();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    if (this.disposed) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    this.stream = stream;
    await context.audioWorklet.addModule("/audio/interview-capture.js");
    if (this.disposed) return;
    this.capture = new AudioWorkletNode(context, "interview-capture");
    this.capture.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (!this.muted && !this.disposed) onAudio(event.data);
    };
    this.input = context.createMediaStreamSource(stream);
    this.silent = context.createGain();
    this.silent.gain.value = 0;
    this.input
      .connect(this.capture)
      .connect(this.silent)
      .connect(context.destination);
  }

  play(encoded: string) {
    const context = this.context;
    if (!context || this.disposed) return;
    const decoded = atob(encoded);
    if (decoded.length % 2 || decoded.length > 2 * 1024 * 1024) {
      throw new Error("语音播放数据异常。");
    }
    if (!decoded.length) return;
    const bytes = Uint8Array.from(decoded, (char) => char.charCodeAt(0));
    const data = new DataView(bytes.buffer);
    const audio = context.createBuffer(1, bytes.length / 2, 24000);
    const samples = audio.getChannelData(0);
    for (let i = 0; i < samples.length; i++)
      samples[i] = data.getInt16(i * 2, true) / 32768;
    this.nextTime = Math.max(context.currentTime + 0.02, this.nextTime);
    if (this.nextTime - context.currentTime > 60)
      throw new Error("语音播放积压，请重新连接。");
    const source = context.createBufferSource();
    source.buffer = audio;
    source.connect(context.destination);
    this.sources.add(source);
    source.onended = () => {
      this.sources.delete(source);
      source.disconnect();
    };
    source.start(this.nextTime);
    this.nextTime += audio.duration;
  }

  interrupt() {
    this.sources.forEach((source) => {
      source.stop();
      source.disconnect();
    });
    this.sources.clear();
    this.nextTime = 0;
  }

  mute(value: boolean) {
    this.muted = value;
    this.stream?.getAudioTracks().forEach((track) => {
      track.enabled = !value;
    });
  }

  stopMicrophone() {
    this.muted = true;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.input?.disconnect();
    this.capture?.disconnect();
    this.silent?.disconnect();
    if (this.capture) this.capture.port.onmessage = null;
  }

  close() {
    this.disposed = true;
    this.stopMicrophone();
    this.interrupt();
    if (this.context && this.context.state !== "closed")
      void this.context.close();
  }
}
