(() => {
  const TARGET_RATE = 16000;
  const CHUNK_SAMPLES = 7680;
  const POST_SPEECH_TAIL_MS = 300;

  class StreamingVoiceInput {
    constructor(callbacks) {
      this.callbacks = callbacks;
      this.socket = null;
      this.stream = null;
      this.audioContext = null;
      this.source = null;
      this.processor = null;
      this.mute = null;
      this.pending = new Float32Array(0);
      this.active = false;
      this.stopRequested = false;
      this.endSent = false;
      this.finalizing = false;
      this.finalizeTimer = null;
      this.endpoint = new window.VoiceShopSpeechEndpoint(() => this.stop());
    }

    start() {
      this.active = true;
      this.stopRequested = false;
      this.endSent = false;
      this.socket = new WebSocket("ws://127.0.0.1:8765");
      this.socket.binaryType = "arraybuffer";
      this.socket.onopen = () => {
        this.socket.send(JSON.stringify({ type: "start" }));
        if (this.stopRequested) this._endSpeech();
      };
      this.socket.onmessage = (event) => this._handleMessage(event.data);
      this.socket.onerror = () => this._fail("无法连接本地语音服务，请确认已使用 FunASR 环境启动项目");
      this.socket.onclose = (event) => {
        if (this.active && event.code !== 1000) this._fail("本地语音连接已中断，请重新录音");
      };
    }

    stop() {
      if (!this.active || this.finalizing) return;
      this.finalizing = true;
      this.callbacks.onState("finalizing");
      this.finalizeTimer = window.setTimeout(() => this._finishCapture(), POST_SPEECH_TAIL_MS);
    }

    async _handleMessage(raw) {
      let message;
      try {
        message = JSON.parse(raw);
      } catch {
        this._fail("本地语音服务返回了无法识别的数据");
        return;
      }

      if (message.type === "status") {
        this.callbacks.onState(message.stage);
      } else if (message.type === "ready") {
        if (this.stopRequested) {
          this._endSpeech();
          return;
        }
        await this._startCapture();
      } else if (message.type === "partial") {
        this.endpoint.markRecognized(message.text, performance.now());
        this.callbacks.onTranscript(message.text, false);
      } else if (message.type === "final") {
        this.active = false;
        this.finalizing = false;
        window.clearTimeout(this.finalizeTimer);
        this._stopCapture();
        this.callbacks.onTranscript(message.text, true);
        this.callbacks.onFinal(message.text);
        this.socket?.close();
      } else if (message.type === "error") {
        this._fail(message.message || "语音识别失败");
      }
    }

    async _startCapture() {
      try {
        if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
          throw new Error("当前浏览器不支持麦克风流式采集");
        }
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: { ideal: true },
            noiseSuppression: { ideal: true },
            autoGainControl: { ideal: true },
          },
        });
        this.audioContext = new AudioContext({ sampleRate: TARGET_RATE });
        if (this.audioContext.sampleRate !== TARGET_RATE) {
          throw new Error("浏览器无法将麦克风音频设置为 16 kHz");
        }
        await this.audioContext.audioWorklet.addModule("/pcm-processor.js");
        this.source = this.audioContext.createMediaStreamSource(this.stream);
        this.processor = new AudioWorkletNode(this.audioContext, "voiceshop-pcm-capture");
        this.mute = this.audioContext.createGain();
        this.mute.gain.value = 0;
        this.processor.port.onmessage = ({ data }) => {
          this._appendAudio(new Float32Array(data.samples));
          this.endpoint.update(data.level, performance.now());
          this.callbacks.onLevel?.(data.level);
        };
        this.source.connect(this.processor).connect(this.mute).connect(this.audioContext.destination);
        this.callbacks.onState("listening");
      } catch (error) {
        this._fail(error.name === "NotAllowedError" ? "麦克风权限未开启，请允许浏览器使用麦克风" : error.message);
      }
    }

    _appendAudio(samples) {
      if (!this.active || this.stopRequested) return;
      const merged = new Float32Array(this.pending.length + samples.length);
      merged.set(this.pending);
      merged.set(samples, this.pending.length);
      let offset = 0;
      while (merged.length - offset >= CHUNK_SAMPLES) {
        this._sendPcm(merged.subarray(offset, offset + CHUNK_SAMPLES));
        offset += CHUNK_SAMPLES;
      }
      this.pending = merged.slice(offset);
    }

    _sendPcm(samples) {
      if (this.socket?.readyState !== WebSocket.OPEN) return;
      const pcm = new Int16Array(samples.length);
      for (let i = 0; i < samples.length; i += 1) {
        const sample = Math.max(-1, Math.min(1, samples[i]));
        pcm[i] = sample < 0 ? sample * 32768 : sample * 32767;
      }
      this.socket.send(pcm.buffer);
    }

    _endSpeech() {
      if (this.endSent || this.socket?.readyState !== WebSocket.OPEN) return;
      if (this.pending.length) this._sendPcm(this.pending);
      this.pending = new Float32Array(0);
      this.endSent = true;
      this.socket.send(JSON.stringify({ type: "speech_end" }));
    }

    _finishCapture() {
      if (!this.active) return;
      this.stopRequested = true;
      this._stopCapture();
      if (this.socket?.readyState === WebSocket.OPEN) this._endSpeech();
    }

    _stopCapture() {
      this.processor?.disconnect();
      this.source?.disconnect();
      this.stream?.getTracks().forEach((track) => track.stop());
      if (this.audioContext && this.audioContext.state !== "closed") this.audioContext.close();
      this.processor = null;
      this.source = null;
      this.stream = null;
      this.audioContext = null;
    }

    _fail(message) {
      if (!this.active) return;
      this.active = false;
      this.finalizing = false;
      window.clearTimeout(this.finalizeTimer);
      this.stopRequested = true;
      this._stopCapture();
      if (this.socket?.readyState === WebSocket.OPEN) this.socket.close();
      this.callbacks.onError(message);
    }
  }

  window.VoiceShopStreamingInput = StreamingVoiceInput;
})();
