(() => {
  const RULES = [
    { from: "缓振", to: "缓震", category: "跑鞋", context: /鞋|跑步|慢跑|运动/ },
    { from: "蓝牙耳几", to: "蓝牙耳机", category: "耳机", context: /蓝牙/ },
    { from: "降噪耳几", to: "降噪耳机", category: "耳机", context: /降噪/ },
  ];

  function correctVoiceTerms(text, products) {
    const categories = new Set(products.map((product) => product.category));
    const changes = [];
    let corrected = text;
    for (const rule of RULES) {
      if (!categories.has(rule.category) || !rule.context.test(text) || !corrected.includes(rule.from)) continue;
      corrected = corrected.split(rule.from).join(rule.to);
      changes.push({ from: rule.from, to: rule.to });
    }
    return { original: text, text: corrected, changes };
  }

  window.correctVoiceTerms = correctVoiceTerms;
})();
