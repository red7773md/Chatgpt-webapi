// ChatGPT Archive terminal. Plain DOM only: text is set with textContent, never innerHTML.
(() => {
  "use strict";

  const POLL_MS = 20000; // the server checks ChatGPT at most this often for one chat
  const root = document.getElementById("app");
  const state = {
    user: null,
    token: null, // { saved, masked, saved_at } from /api/session
    chats: [],
    chatId: null,
    chat: null, // full chat from GET /api/chat/{id}
    draft: "",
    notice: "",
    noticeClass: "",
    timer: null,
  };

  class ApiError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
    }
  }

  async function api(path, options = {}) {
    const init = { credentials: "same-origin", method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    const res = await fetch(path, init);
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      data = null;
    }
    if (!res.ok) {
      const detail = data && (data.detail || data.message);
      throw new ApiError(res.status, typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    return data;
  }

  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children) {
      if (child !== null && child !== undefined && child !== false) node.append(child);
    }
    return node;
  }

  function setNotice(text, cls = "") {
    state.notice = text;
    state.noticeClass = cls;
    const box = document.getElementById("notice");
    if (box) {
      box.className = `status ${cls}`.trim();
      box.textContent = text;
    }
  }

  function fail(err) {
    if (err instanceof ApiError && err.status === 401) {
      state.user = null;
      state.notice = "session expired. log in again.";
      state.noticeClass = "bad";
      render();
      return;
    }
    setNotice(err.message || String(err), "bad");
  }

  const noticeNode = () =>
    el("div", { id: "notice", class: `status ${state.noticeClass}`.trim(), role: "status", "aria-live": "polite", text: state.notice });

  // ----- screens ---------------------------------------------------------------

  function loginScreen() {
    const user = el("input", { class: "field", id: "login-user", autocomplete: "username", "aria-label": "Username" });
    const pass = el("input", {
      class: "field",
      id: "login-pass",
      type: "password",
      autocomplete: "current-password",
      "aria-label": "Password",
    });
    const submit = el("button", { class: "btn", type: "submit", text: "[ AUTHENTICATE ]" });
    const form = el(
      "form",
      {
        class: "login-form",
        onsubmit: async (event) => {
          event.preventDefault();
          submit.disabled = true;
          try {
            await api("/api/auth/login", { method: "POST", body: { username: user.value, password: pass.value } });
            await boot();
          } catch (err) {
            setNotice(err.message, "bad");
            submit.disabled = false;
          }
        },
      },
      el("label", { class: "hint", text: "username" }),
      user,
      el("label", { class: "hint", text: "password" }),
      pass,
      submit,
    );
    return el("section", { class: "panel" }, el("h1", { class: "panel-title", text: "chatgpt // archive" }), form, noticeNode());
  }

  // The line under the session heading: what is saved, and what the last check said.
  function checkLine() {
    const token = state.token || {};
    if (!token.saved) {
      return el("p", { class: "warn", text: token.notice || "no session cookie saved. chats cannot run until one is saved." });
    }
    const check = token.check || {};
    const parts = token.parts === 2 ? "2 parts, .0 and .1" : "1 part";
    const head = `cookie saved (${parts}, ${token.masked}).`;
    const when = check.checked_at ? new Date(check.checked_at).toLocaleString() : "";
    if (check.valid === true) {
      const who = check.account ? ` as ${check.account}` : "";
      return el("p", { class: "ok", text: `${head} session valid${who}. checked ${when}.` });
    }
    if (check.valid === false) {
      return el("p", { class: "bad", text: `${head} ${check.error || "session is not logged in."}` });
    }
    if (check.checked_at) {
      const reason = (check.error || "unknown error").replace(/[.\s]+$/, "");
      return el("p", { class: "warn", text: `${head} could not check: ${reason}. checked ${when}.` });
    }
    return el("p", { class: "warn", text: `${head} not checked yet. press CHECK SESSION.` });
  }

  function noticeFor(token) {
    const check = (token && token.check) || {};
    if (check.valid === true) return ["session valid.", "ok"];
    if (check.valid === false) return ["session is not logged in. copy a fresh cookie and save again.", "bad"];
    if (check.checked_at) return ["could not check the session. see the line above.", "warn"];
    return ["cookie saved. press CHECK SESSION.", "warn"];
  }

  function sessionPanel() {
    const tokenBox = el("textarea", {
      class: "field",
      id: "token-input",
      rows: 4,
      "aria-label": "ChatGPT session cookie",
      placeholder: "paste __Secure-next-auth.session-token.0=... and .1=... (one per line), or the whole cookie header",
    });
    return el(
      "section",
      { class: "panel" },
      el("div", { class: "hint", text: "chatgpt session" }),
      checkLine(),
      tokenBox,
      el(
        "div",
        { class: "composer-row" },
        el("button", {
          class: "btn",
          type: "button",
          text: "[ SAVE COOKIE ]",
          onclick: async () => {
            try {
              state.token = (await api("/api/session/token", { method: "POST", body: { token: tokenBox.value } })).token;
              tokenBox.value = "";
              const [text, cls] = noticeFor(state.token);
              setNotice(text, cls);
              render();
            } catch (err) {
              fail(err);
            }
          },
        }),
        el("button", {
          class: "btn",
          type: "button",
          text: "[ CHECK SESSION ]",
          disabled: !(state.token && state.token.saved),
          onclick: async () => {
            setNotice("checking the session with chatgpt...", "dim");
            try {
              state.token = (await api("/api/session/check", { method: "POST" })).token;
              const [text, cls] = noticeFor(state.token);
              setNotice(text, cls);
              render();
            } catch (err) {
              fail(err);
            }
          },
        }),
        el("button", {
          class: "btn danger",
          type: "button",
          text: "[ CLEAR COOKIE ]",
          onclick: async () => {
            if (!window.confirm("Remove the saved ChatGPT session cookie from this app?")) return;
            try {
              await api("/api/session/token", { method: "DELETE" });
              state.token = { saved: false };
              setNotice("cookie removed.", "warn");
              render();
            } catch (err) {
              fail(err);
            }
          },
        }),
      ),
    );
  }

  function chatList() {
    if (!state.chats.length) return el("p", { class: "dim", text: "no saved chats yet" });
    return el(
      "ul",
      { class: "chat-list", "aria-label": "Saved chats" },
      ...state.chats.map((c) =>
        el(
          "li",
          null,
          el("button", {
            class: `chat-item${c.id === state.chatId ? " current" : ""}`,
            type: "button",
            text: c.title || "untitled",
            onclick: () => openChat(c.id),
          }),
          el("div", {
            class: "dim",
            text: `${(c.updated_at || "").slice(0, 16).replace("T", " ")} · ${c.message_count} msgs${
              c.status === "waiting" ? " · writing" : c.status === "failed" ? " · no reply" : ""
            }`,
          }),
        ),
      ),
    );
  }

  function transcript() {
    const chat = state.chat;
    if (!chat) return el("p", { class: "dim", text: "pick a chat, or type a message to start one." });
    const nodes = (chat.messages || []).map((m) =>
      el(
        "div",
        { class: `msg ${m.role === "user" ? "user" : "model"}` },
        el("div", { class: "who", text: m.role === "user" ? "YOU" : "CHATGPT" }),
        el("pre", { class: "body", text: m.text || "(no text)" }),
      ),
    );
    if (chat.status === "waiting") nodes.push(el("p", { class: "dim pending-line", text: "chatgpt is writing the reply..." }));
    if (chat.status === "failed" && chat.pending && chat.pending.error) {
      nodes.push(el("p", { class: "bad", text: chat.pending.error }));
    }
    return el("div", { class: "transcript", "aria-live": "polite" }, ...nodes);
  }

  function chatPanel() {
    const input = el("textarea", {
      class: "field composer",
      id: "chat-input",
      rows: 4,
      maxlength: 8000,
      "aria-label": "Message",
      placeholder: "Message ChatGPT.  Ctrl+Enter to send.",
      oninput: (event) => {
        state.draft = event.target.value;
      },
      onkeydown: (event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          send();
        }
      },
    });
    input.value = state.draft;
    const waiting = state.chat && state.chat.status === "waiting";
    const sendBtn = el("button", { class: "btn", type: "button", text: "[ SEND ]", disabled: waiting, onclick: () => send() });
    return el(
      "section",
      { class: "chat-main" },
      transcript(),
      noticeNode(),
      input,
      el(
        "div",
        { class: "composer-row" },
        el("button", { class: "btn", type: "button", text: "[ NEW CHAT ]", onclick: () => newChat() }),
        state.chatId
          ? el("button", { class: "btn danger", type: "button", text: "[ DELETE CHAT ]", disabled: waiting, onclick: () => removeChat() })
          : null,
        sendBtn,
      ),
    );
  }

  function appScreen() {
    return el(
      "div",
      null,
      el(
        "div",
        { class: "head-row" },
        el("h1", { class: "panel-title", text: "chatgpt // archive" }),
        el("button", { class: "btn danger", type: "button", text: "[ LOGOUT ]", onclick: () => logout() }),
      ),
      sessionPanel(),
      el("div", { class: "chat-layout" }, el("aside", { class: "chat-side" }, el("div", { class: "actions" }), el("div", { class: "hint", text: "saved chats" }), chatList()), chatPanel()),
    );
  }

  function render() {
    root.replaceChildren(state.user ? appScreen() : loginScreen());
  }

  // ----- chats -------------------------------------------------------------------

  async function refreshList() {
    state.chats = (await api("/api/chat")).chats || [];
  }

  function stopPolling() {
    clearTimeout(state.timer);
    state.timer = null;
  }

  function schedulePoll(id) {
    stopPolling();
    state.timer = setTimeout(() => checkChat(id), POLL_MS);
  }

  async function openChat(id) {
    stopPolling();
    try {
      state.chatId = id;
      state.chat = await api(`/api/chat/${id}`);
      setNotice(`opened "${state.chat.title || "untitled"}".`, "dim");
      if (state.chat.status === "waiting") {
        setNotice("chatgpt is still writing. this page checks every 20 seconds.", "dim");
        schedulePoll(id);
      }
      render();
    } catch (err) {
      fail(err);
    }
  }

  function newChat() {
    stopPolling();
    state.chatId = null;
    state.chat = null;
    setNotice("new conversation. the first message names it.", "dim");
    render();
  }

  async function checkChat(id) {
    state.timer = null;
    if (id !== state.chatId) return;
    try {
      const chat = await api(`/api/chat/${id}`);
      if (id !== state.chatId) return;
      state.chat = chat;
      if (chat.status === "waiting") {
        schedulePoll(id);
        setNotice("chatgpt is still writing. this page checks every 20 seconds.", "dim");
      } else {
        setNotice(chat.status === "failed" ? "no reply." : "reply received.", chat.status === "failed" ? "bad" : "ok");
        await refreshList();
      }
      render();
    } catch (err) {
      fail(err);
    }
  }

  async function send() {
    const text = state.draft.trim();
    if (!text) {
      setNotice("type a message first.", "warn");
      return;
    }
    if (state.chat && state.chat.status === "waiting") {
      setNotice("chatgpt is still answering this chat. wait for the reply.", "warn");
      return;
    }
    setNotice("sending...", "dim");
    try {
      const res = await api("/api/chat/send", { method: "POST", body: { chat_id: state.chatId, message: text } });
      state.draft = "";
      state.chatId = res.chat.id;
      state.chat = await api(`/api/chat/${res.chat.id}`);
      await refreshList();
      if (state.chat.status === "waiting") {
        setNotice("chatgpt is writing. this page checks every 20 seconds.", "dim");
        schedulePoll(state.chatId);
      } else if (state.chat.status === "failed") {
        setNotice("chatgpt did not confirm the message in time. the chat is saved; send it again.", "bad");
      } else {
        setNotice("reply received.", "ok");
      }
      render();
    } catch (err) {
      fail(err);
    }
  }

  async function removeChat() {
    if (!state.chatId) return;
    if (!window.confirm("Delete this chat from the archive? ChatGPT's own history is not touched.")) return;
    try {
      await api(`/api/chat/${state.chatId}`, { method: "DELETE" });
      newChat();
      await refreshList();
      setNotice("chat deleted from the archive.", "warn");
      render();
    } catch (err) {
      fail(err);
    }
  }

  async function logout() {
    stopPolling();
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      state.user = null;
      state.chat = null;
      state.chatId = null;
      state.draft = "";
      setNotice("logged out.", "dim");
      render();
    }
  }

  async function boot() {
    try {
      const me = await api("/api/auth/me");
      state.user = me.logged_in ? me.username : null;
      if (state.user) {
        state.token = await api("/api/session").then((s) => s.token);
        await refreshList();
      }
    } catch (err) {
      state.user = null;
      setNotice(err.message, "bad");
    }
    render();
  }

  boot();
})();
