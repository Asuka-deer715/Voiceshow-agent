class VoiceShopAuth {
  constructor() {
    this.tokenKey = "voiceshop_access_token";
    this.userKey = "voiceshop_user";
    this.token = window.localStorage.getItem(this.tokenKey) || "";
    this.user = this.readUser();
    this.mode = "login";
    this.pendingAction = null;
    this.dialog = document.querySelector("#authDialog");
    this.form = document.querySelector("#authForm");
    this.message = document.querySelector("#authMessage");
    this.submitButton = document.querySelector("#authSubmit");
    this.nicknameField = document.querySelector("#nicknameField");
    this.passwordInput = document.querySelector("#authPassword");
    this.bindEvents();
    this.updateHeader();
  }

  readUser() {
    try {
      return JSON.parse(window.localStorage.getItem(this.userKey) || "null");
    } catch {
      return null;
    }
  }

  bindEvents() {
    document.querySelector("#authButton").addEventListener("click", () => this.open("login"));
    document.querySelector("#logoutButton").addEventListener("click", () => this.logout());
    document.querySelector("[data-auth-close]").addEventListener("click", () => this.dialog.close());
    this.dialog.addEventListener("click", (event) => { if (event.target === this.dialog) this.dialog.close(); });
    this.form.addEventListener("submit", (event) => this.submit(event));
    document.querySelectorAll("[data-auth-mode]").forEach((button) => {
      button.addEventListener("click", () => this.setMode(button.dataset.authMode));
    });
  }

  setMode(mode) {
    this.mode = mode === "register" ? "register" : "login";
    const registering = this.mode === "register";
    document.querySelector("#authTitle").textContent = registering ? "创建账号" : "欢迎回来";
    document.querySelector("#authDescription").textContent = registering ? "注册后即可保存导购会话并管理订单。" : "登录后可保存会话、记录浏览并管理订单。";
    this.nicknameField.classList.toggle("is-hidden", !registering);
    this.passwordInput.autocomplete = registering ? "new-password" : "current-password";
    this.submitButton.textContent = registering ? "注册并登录" : "登录";
    this.message.textContent = "";
    this.message.className = "auth-message";
    document.querySelectorAll("[data-auth-mode]").forEach((button) => {
      const active = button.dataset.authMode === this.mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
  }

  open(mode = "login", message = "") {
    this.setMode(mode);
    this.message.textContent = message;
    if (!this.dialog.open) this.dialog.showModal();
    window.setTimeout(() => document.querySelector("#authEmail").focus(), 0);
  }

  require(action, message = "请先登录后继续。") {
    if (this.isAuthenticated()) return true;
    this.pendingAction = action;
    this.open("login", message);
    return false;
  }

  isAuthenticated() {
    return Boolean(this.token);
  }

  isAdmin() {
    return this.user?.role === "admin";
  }

  async fetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    const response = await window.fetch(url, { ...options, headers });
    if (response.status === 401 && this.token && !url.startsWith("/api/auth/")) {
      this.clearSession();
      this.open("login", "登录已过期，请重新登录。");
    }
    return response;
  }

  async submit(event) {
    event.preventDefault();
    if (!this.form.reportValidity()) return;
    const payload = Object.fromEntries(new FormData(this.form).entries());
    this.submitButton.disabled = true;
    this.submitButton.textContent = this.mode === "register" ? "正在创建账号…" : "正在登录…";
    this.message.textContent = "";
    try {
      const response = await window.fetch(`/api/auth/${this.mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(this.errorMessage(result.error));
      this.token = result.access_token;
      this.user = {
        user_id: result.user_id,
        role: result.role,
        email: payload.email,
        nickname: payload.nickname || payload.email.split("@")[0],
      };
      window.localStorage.setItem(this.tokenKey, this.token);
      window.localStorage.setItem(this.userKey, JSON.stringify(this.user));
      this.updateHeader();
      this.form.reset();
      this.dialog.close();
      window.dispatchEvent(new CustomEvent("voiceshop:auth-changed", { detail: { authenticated: true } }));
      const action = this.pendingAction;
      this.pendingAction = null;
      if (action) await action();
    } catch (error) {
      this.message.textContent = error.message;
      this.message.className = "auth-message error";
    } finally {
      this.submitButton.disabled = false;
      this.submitButton.textContent = this.mode === "register" ? "注册并登录" : "登录";
    }
  }

  errorMessage(code) {
    return ({
      INVALID_SIGNUP: "请输入有效邮箱，密码需为 8–128 位字符。",
      EMAIL_EXISTS: "该邮箱已经注册，请直接登录。",
      INVALID_CREDENTIALS: "邮箱或密码不正确，请重新输入。",
    })[code] || "暂时无法完成操作，请稍后重试。";
  }

  clearSession() {
    this.token = "";
    this.user = null;
    window.localStorage.removeItem(this.tokenKey);
    window.localStorage.removeItem(this.userKey);
    this.updateHeader();
  }

  logout() {
    this.clearSession();
    window.dispatchEvent(new CustomEvent("voiceshop:auth-changed", { detail: { authenticated: false } }));
  }

  updateHeader() {
    const authButton = document.querySelector("#authButton");
    const logoutButton = document.querySelector("#logoutButton");
    authButton.classList.toggle("is-hidden", this.isAuthenticated());
    logoutButton.classList.toggle("is-hidden", !this.isAuthenticated());
    logoutButton.textContent = this.user?.nickname ? `${this.user.nickname} · 退出` : "退出";
  }
}

window.voiceShopAuth = new VoiceShopAuth();
