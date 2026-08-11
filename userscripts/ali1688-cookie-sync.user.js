// ==UserScript==
// @name         1688 Cookie 安全同步
// @namespace    local.ali1688.cookie-sync
// @version      1.0.3
// @description  手动将当前 PC 浏览器的 1688 Cookie 安全同步到 Linux 服务
// @match        https://*.1688.com/*
// @grant        GM_cookie
// @grant        GM_xmlhttpRequest
// @grant        GM_registerMenuCommand
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      *
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
  "use strict";

  if (window.top !== window.self) {
    return;
  }

  const INSTANCE_KEY = "__ALI1688_COOKIE_SYNC_LOADED__";
  if (window[INSTANCE_KEY]) {
    return;
  }
  window[INSTANCE_KEY] = true;

  const ENDPOINT_KEY = "cookie_sync_endpoint";
  const SECRET_KEY = "cookie_sync_shared_secret";
  const REQUIRED_COOKIES = new Set(["_m_h5_tk", "_m_h5_tk_enc"]);
  let operationInProgress = false;

  function notify(message) {
    window.alert(`[1688 Cookie 同步] ${message}`);
  }

  function bytesToHex(bytes) {
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
      "",
    );
  }

  function randomNonce() {
    const bytes = crypto.getRandomValues(new Uint8Array(24));
    return btoa(String.fromCharCode(...bytes))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/g, "");
  }

  async function sha256Hex(data) {
    const digest = await crypto.subtle.digest("SHA-256", data);
    return bytesToHex(new Uint8Array(digest));
  }

  async function hmacHex(secret, message) {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const signature = await crypto.subtle.sign(
      "HMAC",
      key,
      encoder.encode(message),
    );
    return bytesToHex(new Uint8Array(signature));
  }

  function listCookies() {
    return new Promise((resolve, reject) => {
      if (typeof GM_cookie === "undefined" || !GM_cookie.list) {
        reject(new Error("当前脚本管理器不支持 GM_cookie API"));
        return;
      }

      GM_cookie.list({ url: "https://www.1688.com/" }, (cookies, error) => {
        if (error) {
          reject(new Error(error.message || String(error)));
          return;
        }
        resolve(cookies || []);
      });
    });
  }

  function sendRequest(endpoint, body, headers) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: "POST",
        url: endpoint,
        headers,
        data: body,
        timeout: 15000,
        anonymous: true,
        onload: resolve,
        onerror: () => reject(new Error("网络请求失败")),
        ontimeout: () => reject(new Error("请求超时")),
      });
    });
  }

  async function runExclusive(operation) {
    if (operationInProgress) {
      notify("已有操作正在进行，请先完成或关闭当前弹窗");
      return;
    }

    operationInProgress = true;
    try {
      await operation();
    } finally {
      operationInProgress = false;
    }
  }

  async function configureEndpoint() {
    return runExclusive(async () => {
      const current = GM_getValue(
        ENDPOINT_KEY,
        "https://sync.example.com/api/cookie-sync",
      );
      const value = window.prompt(
        "请输入 Cookie 同步 HTTPS 接口地址：",
        current,
      );
      if (value === null) {
        return;
      }

      let parsed;
      try {
        parsed = new URL(value.trim());
      } catch (_) {
        notify("接口地址格式无效");
        return;
      }
      if (parsed.protocol !== "https:") {
        notify("接口必须使用 HTTPS");
        return;
      }

      GM_setValue(ENDPOINT_KEY, parsed.toString());
      notify("接口地址已保存");
    });
  }

  async function configureSecret() {
    return runExclusive(async () => {
      const value = window.prompt(
        "请输入与 Linux 服务一致的共享密钥（至少 32 个字符）：",
        "",
      );
      if (value === null) {
        return;
      }

      const secret = value.trim();
      if (secret.length < 32) {
        notify("共享密钥长度不足 32 个字符");
        return;
      }
      GM_setValue(SECRET_KEY, secret);
      notify("共享密钥已保存到脚本管理器存储");
    });
  }

  async function syncCookies() {
    return runExclusive(async () => {
      try {
        const endpoint = GM_getValue(ENDPOINT_KEY, "").trim();
        const secret = GM_getValue(SECRET_KEY, "");
        if (!endpoint || secret.length < 32) {
          throw new Error("请先通过菜单配置 HTTPS 接口和共享密钥");
        }

        const browserCookies = await listCookies();
        const cookies = browserCookies
          .filter(
            (cookie) =>
              typeof cookie.name === "string" &&
              cookie.name.length > 0 &&
              typeof cookie.value === "string" &&
              cookie.value.length > 0,
          )
          .map((cookie) => ({
            name: cookie.name,
            value: cookie.value,
            domain: typeof cookie.domain === "string" ? cookie.domain : "",
            path: typeof cookie.path === "string" ? cookie.path : "/",
            secure: cookie.secure === true,
            httpOnly: cookie.httpOnly === true,
            expirationDate:
              typeof cookie.expirationDate === "number" &&
              Number.isFinite(cookie.expirationDate)
                ? cookie.expirationDate
                : null,
            sameSite:
              typeof cookie.sameSite === "string" ? cookie.sameSite : null,
          }));

        const names = new Set(cookies.map((cookie) => cookie.name));
        const missing = Array.from(REQUIRED_COOKIES).filter(
          (name) => !names.has(name),
        );
        if (missing.length > 0) {
          throw new Error(
            `浏览器中缺少必要 Cookie：${missing.join(", ")}，请重新登录或刷新 1688`,
          );
        }

        const payload = {
          source: "tampermonkey-1688",
          cookies,
        };
        const body = JSON.stringify(payload);
        const bodyBytes = new TextEncoder().encode(body);
        const timestamp = String(Math.floor(Date.now() / 1000));
        const nonce = randomNonce();
        const bodyHash = await sha256Hex(bodyBytes);
        const signature = await hmacHex(
          secret,
          `${timestamp}\n${nonce}\n${bodyHash}`,
        );

        const response = await sendRequest(endpoint, body, {
          "Content-Type": "application/json",
          "X-Sync-Timestamp": timestamp,
          "X-Sync-Nonce": nonce,
          "X-Sync-Signature": signature,
        });

        let result = {};
        try {
          result = JSON.parse(response.responseText || "{}");
        } catch (_) {
          throw new Error(`服务返回非 JSON 响应（HTTP ${response.status}）`);
        }

        if (response.status < 200 || response.status >= 300) {
          throw new Error(
            result.detail || `同步失败（HTTP ${response.status}）`,
          );
        }

        const expiry = result.earliest_expiry
          ? `，最早到期时间：${result.earliest_expiry}`
          : "";
        notify(`同步成功，共保存 ${result.cookie_count} 个 Cookie${expiry}`);
      } catch (error) {
        notify(error instanceof Error ? error.message : String(error));
      }
    });
  }

  GM_registerMenuCommand("同步 1688 Cookie 到 Linux", syncCookies);
  GM_registerMenuCommand("配置同步接口", configureEndpoint);
  GM_registerMenuCommand("配置共享密钥", configureSecret);
})();
