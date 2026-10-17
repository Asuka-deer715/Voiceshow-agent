const test = require("node:test");
const assert = require("node:assert/strict");

global.window = global;
require("../web/voice-corrections.js");

test("corrects a shoe term while preserving budget, quantity and model", () => {
  const result = correctVoiceTerms("500元以内，2双Nike Pegasus 39跑鞋，缓振好一点", [{ category: "跑鞋" }]);
  assert.equal(result.text, "500元以内，2双Nike Pegasus 39跑鞋，缓震好一点");
  assert.deepEqual(result.changes, [{ from: "缓振", to: "缓震" }]);
});

test("does not rewrite a term without its shopping context", () => {
  const result = correctVoiceTerms("这个设备的缓振怎么样", [{ category: "跑鞋" }]);
  assert.equal(result.text, result.original);
});

test("only applies product terms for categories present in the catalog", () => {
  assert.equal(correctVoiceTerms("我要蓝牙耳几", [{ category: "跑鞋" }]).text, "我要蓝牙耳几");
  assert.equal(correctVoiceTerms("我要蓝牙耳几", [{ category: "耳机" }]).text, "我要蓝牙耳机");
});
