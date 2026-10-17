(() => {
  class StreamingTranscriptBuffer {
    constructor(initialValue, placeholder) {
      this.baseText = initialValue.trim() === placeholder ? "" : initialValue.trim();
      this.lastRenderedValue = initialValue;
      this.transcript = "";
      this.manuallyEdited = false;
    }

    apply(transcript, currentValue) {
      if (currentValue !== this.lastRenderedValue) this.manuallyEdited = true;

      let nextValue = currentValue;
      if (!this.manuallyEdited) {
        nextValue = [this.baseText, transcript].filter(Boolean).join("，");
      } else if (transcript.startsWith(this.transcript)) {
        const delta = transcript.slice(this.transcript.length);
        if (delta) {
          const needsComma = nextValue && !/[\s，。！？、,.!?]$/.test(nextValue) && !/^[，。！？、,.!?]/.test(delta);
          nextValue += `${needsComma ? "，" : ""}${delta}`;
        }
      }

      this.transcript = transcript;
      this.lastRenderedValue = nextValue;
      return nextValue;
    }
  }

  window.StreamingTranscriptBuffer = StreamingTranscriptBuffer;
})();
