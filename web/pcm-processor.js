class VoiceShopPcmProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0]?.[0];
    if (channel?.length) {
      const copy = channel.slice();
      let energy = 0;
      for (let i = 0; i < channel.length; i += 1) energy += channel[i] * channel[i];
      const level = Math.sqrt(energy / channel.length);
      this.port.postMessage({ samples: copy.buffer, level }, [copy.buffer]);
    }
    return true;
  }
}

registerProcessor("voiceshop-pcm-capture", VoiceShopPcmProcessor);
