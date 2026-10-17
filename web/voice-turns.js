(() => {
  class VoiceShopVoiceTurns {
    constructor({ listen, answer, speak, onChange }) {
      this.listen = listen;
      this.answer = answer;
      this.speak = speak;
      this.onChange = onChange;
      this.active = false;
      this.generation = 0;
    }

    start() {
      if (this.active) return;
      this.active = true;
      this.generation += 1;
      this.onChange(true);
      this.listen(true);
    }

    stop() {
      if (!this.active) return;
      this.active = false;
      this.generation += 1;
      this.onChange(false);
    }

    async complete(transcript) {
      if (!this.active) return;
      if (!transcript.trim()) {
        this.stop();
        return;
      }

      const generation = this.generation;
      const response = await this.answer();
      if (!this.active || generation !== this.generation) return;
      if (!response) {
        this.stop();
        return;
      }

      const spoken = await this.speak(response);
      if (!this.active || generation !== this.generation) return;
      if (spoken) this.listen(false);
      else this.stop();
    }
  }

  window.VoiceShopVoiceTurns = VoiceShopVoiceTurns;
})();
