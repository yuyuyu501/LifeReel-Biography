/* Resample microphone audio to 16 kHz PCM16 in 20 ms frames. */
class InterviewCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Int16Array(320);
    this.index = 0;
    this.weight = 0;
    this.sum = 0;
    this.ratio = sampleRate / 16000;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    for (const sample of input) {
      let available = 1;
      while (available > 0.000001) {
        const take = Math.min(available, this.ratio - this.weight);
        this.sum += sample * take;
        this.weight += take;
        available -= take;
        if (this.weight >= this.ratio - 0.000001) {
          const value = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.frame[this.index++] = Math.round(value * (value < 0 ? 32768 : 32767));
          this.sum = this.weight = 0;
          if (this.index === 320) {
            const buffer = new ArrayBuffer(640);
            const view = new DataView(buffer);
            for (let i = 0; i < 320; i++) view.setInt16(i * 2, this.frame[i], true);
            this.port.postMessage(buffer, [buffer]);
            this.index = 0;
          }
        }
      }
    }
    return true;
  }
}

registerProcessor("interview-capture", InterviewCapture);
