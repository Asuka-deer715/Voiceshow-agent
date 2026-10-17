const test = require("node:test");
const assert = require("node:assert/strict");

global.window = global;
require("../web/voice-endpoint.js");

test("finalizes once after a spoken phrase and a sustained pause", () => {
  let endings = 0;
  const endpoint = new VoiceShopSpeechEndpoint(() => { endings += 1; });
  for (let now = 0; now < 240; now += 8) endpoint.update(0.02, now);
  for (let now = 240; now < 1500; now += 8) endpoint.update(0.001, now);
  assert.equal(endings, 1);
});

test("a brief pause and a quiet final syllable keep the turn open", () => {
  let endings = 0;
  const endpoint = new VoiceShopSpeechEndpoint(() => { endings += 1; });
  for (let now = 0; now < 240; now += 8) endpoint.update(0.02, now);
  for (let now = 240; now < 750; now += 8) endpoint.update(0.001, now);
  endpoint.update(0.007, 760);
  endpoint.update(0.001, 1600);
  assert.equal(endings, 0);
  endpoint.update(0.001, 1870);
  assert.equal(endings, 1);
});

test("recognition can establish speech when the audio level is low", () => {
  let endings = 0;
  const endpoint = new VoiceShopSpeechEndpoint(() => { endings += 1; });
  endpoint.markRecognized("你好", 100);
  endpoint.update(0.001, 1200);
  assert.equal(endings, 1);
});
