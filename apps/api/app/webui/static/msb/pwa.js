(() => {
  "use strict";

  const DISMISS_KEY = "msb-pwa-install-dismissed";
  const DISMISS_DAYS = 14;

  const isStandalone = () => {
    if (window.matchMedia("(display-mode: standalone)").matches) return true;
    if (window.navigator.standalone === true) return true;
    return false;
  };

  const dismissedRecently = () => {
    try {
      const raw = localStorage.getItem(DISMISS_KEY);
      if (!raw) return false;
      const ts = Number(raw);
      if (!Number.isFinite(ts)) return true;
      return Date.now() - ts < DISMISS_DAYS * 24 * 60 * 60 * 1000;
    } catch (_) {
      return false;
    }
  };

  const markDismissed = () => {
    try { localStorage.setItem(DISMISS_KEY, String(Date.now())); } catch (_) { /* ignore */ }
  };

  const isiOS = () => {
    const ua = window.navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  };

  const isSafari = () => {
    const ua = window.navigator.userAgent || "";
    return /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|Chrome|Android/.test(ua);
  };

  let deferredPrompt = null;
  let banner = null;

  const hideBanner = () => {
    if (!banner) return;
    banner.classList.remove("is-visible");
    window.setTimeout(() => {
      if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
      banner = null;
    }, 220);
  };

  const showBanner = ({ mode }) => {
    if (banner || isStandalone() || dismissedRecently()) return;

    banner = document.createElement("div");
    banner.className = "msb-pwa-banner";
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-label", "Установить приложение MSB");
    const hint = mode === "ios"
      ? "Нажмите «Поделиться» в Safari и выберите «На экран „Домой“»."
      : mode === "native"
        ? "Откроется как отдельное приложение, без строки браузера."
        : "В меню браузера выберите «Установить приложение» или «Добавить на главный экран».";
    banner.innerHTML =
      '<div class="msb-pwa-banner__icon" aria-hidden="true">MSB</div>' +
      '<div class="msb-pwa-banner__copy">' +
        "<strong>Установить MSB</strong>" +
        "<span>" + hint + "</span>" +
      "</div>" +
      (mode === "native"
        ? '<button type="button" class="msb-pwa-banner__install" data-pwa-install>Установить</button>'
        : "") +
      '<button type="button" class="msb-pwa-banner__close" data-pwa-dismiss aria-label="Закрыть">×</button>';
    document.body.appendChild(banner);
    requestAnimationFrame(() => banner.classList.add("is-visible"));

    const closeBtn = banner.querySelector("[data-pwa-dismiss]");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        markDismissed();
        hideBanner();
      });
    }
    const installBtn = banner.querySelector("[data-pwa-install]");
    if (installBtn) {
      installBtn.addEventListener("click", async () => {
        if (!deferredPrompt) return;
        deferredPrompt.prompt();
        try {
          await deferredPrompt.userChoice;
        } catch (_) { /* ignore */ }
        deferredPrompt = null;
        markDismissed();
        hideBanner();
      });
    }
  };

  const registerWorker = () => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).catch(() => {});
  };

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    showBanner({ mode: "native" });
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    markDismissed();
    hideBanner();
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", registerWorker);
  } else {
    registerWorker();
  }

  window.setTimeout(() => {
    if (deferredPrompt || isStandalone() || dismissedRecently()) return;
    if (isiOS() && isSafari()) {
      showBanner({ mode: "ios" });
      return;
    }
    showBanner({ mode: "manual" });
  }, 1200);
})();
