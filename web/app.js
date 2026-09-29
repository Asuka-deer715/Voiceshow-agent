const queryInput = document.querySelector("#query");
const runButton = document.querySelector("#runButton");
const speakButton = document.querySelector("#speakButton");
const evalButton = document.querySelector("#evalButton");
const answerTitle = document.querySelector("#answerTitle");
const answerText = document.querySelector("#answerText");
const thinkingText = document.querySelector("#thinkingText");
const micButton = document.querySelector("#micButton");
const voiceStatus = document.querySelector("#voiceStatus");
const userChat = document.querySelector(".user-chat");
const recommendationList = document.querySelector("#recommendationList");
const recommendationCount = document.querySelector("#assistantRecommendationCount");
const catalogGrid = document.querySelector("#catalogGrid");
const catalogSummary = document.querySelector("#catalogSummary");
const catalogTitle = document.querySelector("#catalogTitle");
const sortChip = document.querySelector("#sortChip");
const candidateCount = document.querySelector("#candidateCount");
const slotCount = document.querySelector("#slotCount");
const traceCount = document.querySelector("#traceCount");
const slotList = document.querySelector("#slotList");
const traceList = document.querySelector("#traceList");
const traceId = document.querySelector("#traceId");
const metricGrid = document.querySelector("#metricGrid");
const productDetail = document.querySelector("#productDetail");
const conversationMessages = document.querySelector("#conversationMessages");
const detailName = document.querySelector("#detailName");
const detailDescription = document.querySelector("#detailDescription");
const detailPrice = document.querySelector("#detailPrice");
const detailOrderButton = document.querySelector("#detailOrderButton");
const orderList = document.querySelector("#orderList");
const sessionList = document.querySelector("#sessionList");
const newSessionButton = document.querySelector("#newSessionButton");

let latestResponse = "";
let allProducts = [];
let activeCategory = "全部";
let sessionId = window.localStorage.getItem("voiceshop_session_id") || null;
let recognition = null;
let isListening = false;
let autoVoiceEnabled = window.localStorage.getItem("voiceshop_auto_voice") !== "off";
let progressTimer = null;

const slotLabels = { category: "商品类别", budget_max: "预算上限", usage_scene: "使用场景", brand_preference: "品牌偏好", must_have: "核心偏好", avoid: "规避条件" };
const metricLabels = { total_cases: "评测样本", slot_f1: "Slot-F1", recall_at_5: "Recall@5", clarification_accuracy: "澄清准确率" };

function switchView(viewName) {
  document.querySelectorAll("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.id === viewName));
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === viewName));
  history.replaceState(null, "", `#${viewName}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>\"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" })[character]);
}

function clearConversation() {
  conversationMessages.querySelectorAll(".history-message").forEach((message) => message.remove());
  latestResponse = "";
  answerTitle.textContent = "等待你的需求";
  answerText.textContent = "";
  renderSlots({});
  renderRecommendations([]);
  traceCount.textContent = "0";
  traceId.textContent = "trace pending";
  traceList.innerHTML = "";
}

function renderSessionList(sessions = []) {
  if (!sessions.length) {
    sessionList.innerHTML = "<p class='session-empty'>还没有历史会话</p>";
    return;
  }
  sessionList.innerHTML = sessions.map((session) => {
    const title = (session.title || "新对话").trim().slice(0, 28);
    const active = session.id === sessionId ? " active" : "";
    return `<div class="session-row"><button class="session-item${active}" type="button" data-session-id="${session.id}"><strong>${escapeHtml(title)}</strong><small>${session.message_count} 条消息</small></button><button class="session-delete" type="button" data-session-delete="${session.id}" aria-label="删除会话" title="删除会话">×</button></div>`;
  }).join("");
}

async function loadSessions() {
  const data = await (await fetch("/api/sessions")).json();
  renderSessionList(data.sessions || []);
  if (sessionId && !data.sessions.some((session) => session.id === sessionId)) {
    sessionId = null;
    window.localStorage.removeItem("voiceshop_session_id");
  }
}

async function loadSessionHistory(targetSessionId) {
  const response = await fetch(`/api/sessions/${encodeURIComponent(targetSessionId)}`);
  if (!response.ok) throw new Error("历史会话加载失败");
  const data = await response.json();
  sessionId = targetSessionId;
  window.localStorage.setItem("voiceshop_session_id", sessionId);
  clearConversation();
  (data.messages || []).forEach((message) => {
    appendConversationMessage(message.role === "USER" ? "user-chat" : "assistant-chat", message.content);
    if (message.role === "ASSISTANT") latestResponse = message.content;
  });
  renderSlots(data.session?.slots || {});
  answerTitle.textContent = "历史会话";
  await loadSessions();
}

async function deleteSession(targetSessionId) {
  const confirmed = window.confirm("删除后将无法恢复这段会话，确定删除吗？");
  if (!confirmed) return;
  const response = await fetch("/api/sessions/delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: targetSessionId }) });
  if (!response.ok) throw new Error("历史会话删除失败");
  if (targetSessionId === sessionId) startNewSession();
  await loadSessions();
}

function startNewSession() {
  sessionId = null;
  window.localStorage.removeItem("voiceshop_session_id");
  queryInput.value = "";
  clearConversation();
  loadSessions();
}

function formatValue(value) {
  if (Array.isArray(value)) return value.length ? value.join("、") : "未命中";
  if (value === null || value === undefined || value === "") return "未识别";
  return String(value);
}

function visualClass(category = "") {
  if (category.includes("耳机")) return "headphone-visual";
  if (category.includes("手表")) return "watch-visual";
  if (category.includes("口红")) return "lipstick-visual";
  return "shoe-visual";
}

function activeSlotCount(slots = {}) {
  return Object.values(slots).filter((value) => Array.isArray(value) ? value.length : value !== null && value !== undefined && value !== "").length;
}

function renderSlots(slots = {}) {
  slotCount.textContent = activeSlotCount(slots);
  slotList.innerHTML = Object.entries(slotLabels).map(([key, label]) => {
    const value = key === "budget_max" && slots[key] ? `${slots[key]} 元` : formatValue(slots[key]);
    return `<div><dt>${label}</dt><dd>${value}</dd></div>`;
  }).join("");
}

function buildReason(item, slots = {}) {
  const reasons = [];
  if (slots.budget_max && item.price <= slots.budget_max) reasons.push(`价格 ${item.price} 元，在预算内`);
  const sceneLabels = { running: "适合跑步训练", commute: "适合日常通勤", noise_cancel: "适合通勤和办公", business: "适合正式场景" };
  if (slots.usage_scene && (item.scene_tags || []).includes(slots.usage_scene)) reasons.push(sceneLabels[slots.usage_scene] || "使用场景匹配");
  const matched = (slots.must_have || []).filter((tag) => (item.feature_tags || []).includes(tag));
  const featureLabels = { light: "轻量设计，适合长时间行走", cushion: "缓震配置，脚感更舒适", stable: "稳定支撑，适合需要控制足部晃动的用户", battery: "续航表现更适合长时间使用", noise_cancel: "具备降噪能力，适合嘈杂环境", durable: "耐用性较好，适合日常长期使用" };
  matched.forEach((tag) => reasons.push(featureLabels[tag] || `具备${tag}功能`));
  if (slots.brand_preference && item.brand.toLowerCase() === slots.brand_preference.toLowerCase()) reasons.push(`符合 ${item.brand} 品牌偏好`);
  if (reasons.length < 2 && item.stock > 0) reasons.push("当前有库存，可及时下单");
  return reasons.length ? reasons.slice(0, 2).join(" · ") : "商品信息与当前需求整体匹配";
}

function productCard(item, mode = "catalog", slots = {}) {
  const score = item.score ? `<span class="score">匹配度 ${Number(item.score).toFixed(2)}</span>` : "";
  const reason = mode === "recommendation" ? `<p class="reason">推荐理由：${buildReason(item, slots)}</p>` : "";
  const visual = item.image ? `<img class="product-image" src="${item.image}" alt="${item.name}">` : `<div class="product-visual ${visualClass(item.category)}"></div>`;
  return `<article class="${mode === "catalog" ? "catalog-card" : "product-card"}">
    <div class="visual">${visual}</div>
    <div>${score}<h3>${item.name}</h3></div>
    <div class="price-line"><span class="price">${item.price} 元</span><span class="stock">库存 ${item.stock}</span></div>
    <div class="meta"><span>${item.brand}</span><span>${item.category}</span>${(item.scene_tags || []).slice(0, 2).map((tag) => `<span>${tag}</span>`).join("")}</div>
    <p>${item.description}</p>${reason}<div class="product-actions"><button type="button" data-product-view="${item.id}">查看详情</button><button type="button" data-product-order="${item.id}">立即下单</button></div>
  </article>`;
}

function renderCatalog() {
  const products = activeCategory === "全部" ? allProducts : allProducts.filter((item) => item.category === activeCategory);
  catalogTitle.textContent = activeCategory === "全部" ? "全部商品" : activeCategory;
  catalogSummary.textContent = `${products.length} 件商品`;
  sortChip.textContent = "精选商品";
  catalogGrid.innerHTML = products.length ? products.map((item) => productCard(item)).join("") : "<div class='catalog-empty'>暂时没有符合条件的商品</div>";
}

function showProductDetail(productId) {
  const item = allProducts.find((product) => product.id === Number(productId));
  if (!item) return;
  if (!productDetail.querySelector("[data-detail-close]")) {
    productDetail.insertAdjacentHTML("afterbegin", '<button class="detail-close" type="button" data-detail-close aria-label="关闭商品详情">×</button>');
  }
  detailName.textContent = item.name;
  detailDescription.innerHTML = `<strong>${item.brand} · ${item.category}</strong><br>${item.description}<br><span>适用场景：${(item.scene_tags || []).join("、") || "日常使用"}　|　功能特点：${(item.feature_tags || []).join("、") || "基础功能"}　|　库存：${item.stock} 件</span>`;
  detailPrice.textContent = `${item.price} 元`;
  detailOrderButton.dataset.productId = item.id;
  productDetail.classList.remove("is-hidden");
  switchView("catalog");
  productDetail.scrollIntoView({ behavior: "smooth", block: "center" });
  fetch("/api/behavior", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ product_id: item.id, event: "view" }) });
}

async function createOrder(productId) {
  const response = await fetch("/api/orders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ product_id: Number(productId), session_id: sessionId }) });
  if (!response.ok) throw new Error("订单创建失败");
  await loadOrders();
  switchView("orders");
}

async function loadOrders() {
  const data = await (await fetch("/api/orders")).json();
  orderList.innerHTML = data.orders.length ? data.orders.map((order) => `<article class="order-item"><div><strong>${order.order_no}</strong><span>商品 ID ${order.product_id} · ${order.quantity} 件</span></div><div class="order-actions"><b>${order.status}</b><button type="button" data-order-delete="${order.order_no}">删除订单</button></div></article>`).join("") : "<div class='catalog-empty'>暂时还没有订单</div>";
}

async function deleteOrder(orderNo) {
  const response = await fetch("/api/orders/delete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order_no: orderNo }) });
  if (!response.ok) throw new Error("订单删除失败");
  await loadOrders();
}

function normalizeRecommendationCategory(category = "") {
  if (["鞋子", "鞋", "运动鞋", "跑步鞋", "跑鞋"].includes(category)) return "跑鞋";
  if (["耳机", "蓝牙耳机", "降噪耳机"].includes(category)) return "耳机";
  if (["手表", "腕表"].includes(category)) return "手表";
  return category;
}

function renderRecommendations(items = [], slots = {}) {
  const category = normalizeRecommendationCategory(slots.category || "");
  const visibleItems = category ? items.filter((item) => item.category === category) : items;
  candidateCount.textContent = visibleItems.length;
  recommendationCount.textContent = visibleItems.length ? `${visibleItems.length} 件推荐` : "尚未筛选";
  if (!visibleItems.length) {
    recommendationList.className = "recommendation-list empty";
    recommendationList.textContent = "你的推荐商品会显示在这里";
    return;
  }
  recommendationList.className = "recommendation-list";
  recommendationList.innerHTML = visibleItems.map((item) => productCard(item, "recommendation", slots)).join("");
}

function startAgentProgress(query) {
  const knowledgeQuery = ["退货", "退款", "换货", "售后", "发货", "物流", "保修", "怎么寄回", "多久"].some((keyword) => query.includes(keyword));
  const stages = knowledgeQuery ? [
    ["正在识别用户问题", "判断问题类型与处理方向"],
    ["正在检索知识库", "匹配售后、物流与服务资料"],
    ["正在核对相关依据", "整理可引用的知识内容"],
    ["正在总结，为您提供相关解答", "生成最终回复"]
  ] : [
    ["正在识别用户问题", "理解商品类别与购买意图"],
    ["正在整理购物偏好", "提取预算、场景和功能需求"],
    ["正在检索商品", "筛选符合条件的候选商品"],
    ["正在比较匹配度", "综合预算、场景与商品特征"],
    ["正在总结，为您提供相关解答", "生成推荐理由"]
  ];
  let stageIndex = 0;
  const showStage = () => {
    const [title, detail] = stages[stageIndex];
    answerTitle.textContent = title;
    recommendationCount.textContent = `处理中 · ${stageIndex + 1}/${stages.length}`;
    recommendationList.className = "recommendation-list progress-state";
    recommendationList.innerHTML = `<div class="progress-message"><span class="progress-spinner"></span><div><strong>${title}</strong><small>${detail}</small></div></div>`;
  };
  showStage();
  progressTimer = window.setInterval(() => {
    if (stageIndex < stages.length - 1) {
      stageIndex += 1;
      showStage();
    }
  }, 650);
}

function stopAgentProgress() {
  if (progressTimer) window.clearInterval(progressTimer);
  progressTimer = null;
}

function summarizeTraceStep(step) {
  if (step.node === "extract_slots") return `识别 ${activeSlotCount(step.slots || {})} 组需求`;
  if (step.node === "clarification_gate") return step.need_clarification ? "缺少关键信息，向用户追问" : "需求完整，进入商品召回";
  if (step.node === "retrieve_products") return `召回 ${step.candidate_count || 0} 个候选商品`;
  if (step.node === "generate_recommendation") return `输出 Top ${step.top_ids?.length || 0} 推荐`;
  return step.node;
}

function renderTrace(result) {
  const trace = result.trace || [];
  traceCount.textContent = trace.length;
  traceId.textContent = result.trace_id ? `trace ${result.trace_id.slice(0, 8)}` : "trace pending";
  traceList.innerHTML = trace.map((step, index) => `<li><strong>${index + 1}. ${step.label || step.node}</strong><span>${summarizeTraceStep(step)}</span><code>${JSON.stringify(step, null, 2)}</code></li>`).join("");
}

function renderResult(result) {
  latestResponse = result.response || "";
  const slots = result.slots || {};
  answerTitle.textContent = result.status === "clarify" ? "还需要一点信息" : (result.recommendations?.length ? "已完成筛选" : "知识库回答");
  answerText.textContent = latestResponse || "没有返回内容";
  userChat.textContent = queryInput.value.trim();
  renderSlots(slots);
  renderRecommendations(result.recommendations || [], slots);
  renderTrace(result);
}

function appendConversationMessage(className, text, thinking = false) {
  const message = document.createElement("div");
  message.className = `message history-message ${className}`;
  if (thinking) {
    message.innerHTML = `${text}<span class="thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span>`;
  } else {
    message.textContent = text;
  }
  conversationMessages.appendChild(message);
  conversationMessages.scrollTop = conversationMessages.scrollHeight;
  return message;
}

function hideLegacyMessagePlaceholders() {
  userChat.classList.add("is-hidden");
  thinkingText.classList.add("is-hidden");
  answerText.classList.add("is-hidden");
}

async function runAgent() {
  const query = queryInput.value.trim();
  if (!query) return;
  runButton.disabled = true;
  hideLegacyMessagePlaceholders();
  appendConversationMessage("user-chat", query);
  const thinkingMessage = appendConversationMessage("thinking-chat", "Agent 正在分析", true);
  runButton.innerHTML = "正在筛选 <span>…</span>";
  userChat.textContent = query;
  userChat.classList.remove("is-hidden");
  userChat.classList.add("is-hidden");
  answerText.classList.add("is-hidden");
  thinkingText.classList.remove("is-hidden");
  thinkingText.classList.add("is-hidden");
  startAgentProgress(query);
  const startedAt = Date.now();
  try {
    const responsePromise = fetch("/api/recommend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, session_id: sessionId }) });
    const response = await responsePromise;
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "推荐失败");
    sessionId = result.session_id || sessionId;
    if (sessionId) window.localStorage.setItem("voiceshop_session_id", sessionId);
    await new Promise((resolve) => setTimeout(resolve, Math.max(0, 850 - (Date.now() - startedAt))));
    thinkingText.classList.add("is-hidden");
    answerText.classList.remove("is-hidden");
    thinkingMessage.remove();
    answerText.classList.add("is-hidden");
    stopAgentProgress();
    appendConversationMessage("assistant-chat", result.response || "没有返回内容");
    renderResult(result);
    if (autoVoiceEnabled) speakText(result.response || "没有返回内容");
    await loadSessions();
  } catch (error) {
    thinkingText.classList.add("is-hidden");
    answerText.classList.remove("is-hidden");
    thinkingMessage.remove();
    answerText.classList.add("is-hidden");
    stopAgentProgress();
    appendConversationMessage("assistant-chat", error.message);
    answerTitle.textContent = "暂时无法完成筛选";
    answerText.textContent = error.message;
    renderRecommendations([]);
  } finally {
    runButton.disabled = false;
    runButton.innerHTML = "开始筛选 <span>↗</span>";
  }
}

function updateVoiceButton() {
  speakButton.textContent = autoVoiceEnabled ? "语音回复：开" : "语音回复：关";
  speakButton.setAttribute("aria-pressed", String(autoVoiceEnabled));
  speakButton.title = autoVoiceEnabled ? "关闭自动语音回复" : "开启自动语音回复";
}

function speakText(text) {
  if (!text || !("speechSynthesis" in window)) {
    setVoiceStatus("当前浏览器不支持语音合成，请使用文字回复");
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
}

function speakLatestResponse() {
  speakText(latestResponse);
}

function toggleAutoVoice() {
  autoVoiceEnabled = !autoVoiceEnabled;
  window.localStorage.setItem("voiceshop_auto_voice", autoVoiceEnabled ? "on" : "off");
  updateVoiceButton();
  if (!autoVoiceEnabled && "speechSynthesis" in window) window.speechSynthesis.cancel();
  setVoiceStatus(autoVoiceEnabled ? "自动语音回复已开启" : "自动语音回复已关闭");
  if (autoVoiceEnabled) speakLatestResponse();
}

function setVoiceStatus(message) {
  voiceStatus.textContent = message;
}

function toggleVoiceInput() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    setVoiceStatus("当前浏览器不支持语音识别，请使用文字输入");
    return;
  }
  if (isListening) {
    recognition.stop();
    return;
  }

  const originalText = queryInput.value.trim() === "今天我想买个鞋子" ? "" : queryInput.value.trim();
  recognition = new Recognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onstart = () => {
    isListening = true;
    micButton.classList.add("listening");
    micButton.setAttribute("aria-pressed", "true");
    micButton.setAttribute("aria-label", "停止语音输入");
    setVoiceStatus("正在聆听，请说出你的需求…");
  };
  recognition.onresult = (event) => {
    const transcript = Array.from(event.results).map((result) => result[0].transcript).join("");
    queryInput.value = [originalText, transcript].filter(Boolean).join("，");
  };
  recognition.onerror = (event) => {
    setVoiceStatus(event.error === "not-allowed" ? "麦克风权限未开启，请允许浏览器使用麦克风" : "没有听清，可以再说一次");
  };
  recognition.onend = () => {
    isListening = false;
    micButton.classList.remove("listening");
    micButton.setAttribute("aria-pressed", "false");
    micButton.setAttribute("aria-label", "开始语音输入");
    if (queryInput.value.trim()) setVoiceStatus("已识别，可以检查内容后发送");
  };
  recognition.start();
}

async function refreshEval() {
  evalButton.disabled = true;
  try {
    const report = await (await fetch("/api/eval")).json();
    metricGrid.innerHTML = Object.entries(metricLabels).map(([key, label]) => {
      const raw = report[key];
      const value = typeof raw === "number" && raw <= 1 ? raw.toFixed(4) : raw;
      return `<div class="metric"><strong>${value}</strong><span>${label}</span></div>`;
    }).join("");
  } finally {
    evalButton.disabled = false;
  }
}

async function loadCatalog() {
  const data = await (await fetch("/api/products")).json();
  allProducts = data.products || [];
  renderCatalog();
}

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
document.querySelectorAll("[data-query]").forEach((button) => button.addEventListener("click", () => { queryInput.value = button.dataset.query; switchView("dialogue"); runAgent(); }));
document.querySelectorAll("[data-category]").forEach((button) => button.addEventListener("click", () => {
  activeCategory = button.dataset.category;
  document.querySelectorAll("[data-category]").forEach((item) => item.classList.toggle("active", item === button));
  renderCatalog();
}));
document.addEventListener("click", (event) => {
  const deleteSessionButton = event.target.closest("[data-session-delete]");
  if (deleteSessionButton) {
    deleteSession(deleteSessionButton.dataset.sessionDelete).catch((error) => setVoiceStatus(error.message));
    return;
  }
  const sessionButton = event.target.closest("[data-session-id]");
  if (sessionButton) loadSessionHistory(sessionButton.dataset.sessionId).catch((error) => { setVoiceStatus(error.message); });
  const detailClose = event.target.closest("[data-detail-close]");
  if (detailClose || event.target === productDetail) productDetail.classList.add("is-hidden");
  const detailButton = event.target.closest("[data-product-view]");
  const orderButton = event.target.closest("[data-product-order]");
  if (detailButton) showProductDetail(detailButton.dataset.productView);
  if (orderButton) createOrder(orderButton.dataset.productOrder).catch((error) => { answerText.textContent = error.message; });
  const deleteButton = event.target.closest("[data-order-delete]");
  if (deleteButton) deleteOrder(deleteButton.dataset.orderDelete).catch((error) => { orderList.insertAdjacentHTML("afterbegin", `<div class='catalog-empty'>${error.message}</div>`); });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") productDetail.classList.add("is-hidden");
});
detailOrderButton.addEventListener("click", () => createOrder(detailOrderButton.dataset.productId));

runButton.addEventListener("click", runAgent);
newSessionButton.addEventListener("click", startNewSession);
speakButton.addEventListener("click", toggleAutoVoice);
micButton.addEventListener("click", toggleVoiceInput);
evalButton.addEventListener("click", refreshEval);
queryInput.addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) runAgent(); });

const initialView = window.location.hash.slice(1);
if (["dialogue", "catalog", "scenes", "orders"].includes(initialView)) switchView(initialView);
updateVoiceButton();
loadCatalog();
loadOrders();
refreshEval();
loadSessions().then(() => {
  if (sessionId) loadSessionHistory(sessionId).catch(() => startNewSession());
});
