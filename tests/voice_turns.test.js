const test = require("node:test");
const assert = require("node:assert/strict");

global.window = global;
require("../web/voice-turns.js");

test("submits the final transcript and listens again after speech ends", async () => {
  const calls = [];
  const turns = new VoiceShopVoiceTurns({
    listen: (firstTurn) => calls.push(["listen", firstTurn]),
    answer: async () => { calls.push(["answer"]); return "找到两双跑鞋"; },
    speak: async (text) => { calls.push(["speak", text]); return true; },
    onChange: () => {},
  });

  turns.start();
  await turns.complete("我要买跑鞋");
  assert.deepEqual(calls, [["listen", true], ["answer"], ["speak", "找到两双跑鞋"], ["listen", false]]);
});

test("stopping during speech prevents the microphone from reopening", async () => {
  const calls = [];
  let finishSpeech;
  const turns = new VoiceShopVoiceTurns({
    listen: (firstTurn) => calls.push(["listen", firstTurn]),
    answer: async () => "回复",
    speak: () => new Promise((resolve) => { finishSpeech = resolve; }),
    onChange: () => {},
  });

  turns.start();
  const completion = turns.complete("你好");
  await Promise.resolve();
  turns.stop();
  finishSpeech(true);
  await completion;
  assert.deepEqual(calls, [["listen", true]]);
});
