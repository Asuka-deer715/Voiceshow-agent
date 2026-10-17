(() => {
  const SILENCE_MS = 1100;
  const MIN_SPEECH_MS = 160;

  class VoiceShopSpeechEndpoint {
    constructor(onEnd) {
      this.onEnd = onEnd;
      this.noiseFloor = 0.001;
      this.lastSampleAt = null;
      this.lastVoiceAt = null;
      this.voicedMs = 0;
      this.speechSeen = false;
      this.ended = false;
    }

    update(level, now) {
      if (this.ended) return;
      const frameMs = this.lastSampleAt === null ? 8 : Math.min(50, now - this.lastSampleAt);
      this.lastSampleAt = now;
      const voiced = level >= Math.max(0.006, this.noiseFloor * 3);

      if (voiced) {
        this.voicedMs += frameMs;
        this.lastVoiceAt = now;
        if (this.voicedMs >= MIN_SPEECH_MS) this.speechSeen = true;
      } else {
        this.noiseFloor = this.noiseFloor * 0.98 + level * 0.02;
        if (!this.speechSeen && this.lastVoiceAt !== null && now - this.lastVoiceAt > 300) this.voicedMs = 0;
      }

      if (this.speechSeen && this.lastVoiceAt !== null && now - this.lastVoiceAt >= SILENCE_MS) {
        this.ended = true;
        this.onEnd();
      }
    }

    markRecognized(text, now) {
      if (!text.trim() || this.ended) return;
      this.speechSeen = true;
      this.lastVoiceAt = now;
    }
  }

  window.VoiceShopSpeechEndpoint = VoiceShopSpeechEndpoint;
})();
