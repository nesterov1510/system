"use client";

import { useEffect, useState } from "react";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

function isStandalone() {
  return window.matchMedia("(display-mode: standalone)").matches ||
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
}

function isIos() {
  return /iphone|ipad|ipod/i.test(window.navigator.userAgent) ||
    (window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1);
}

export default function InstallPrompt() {
  const [installEvent, setInstallEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [showIosHelp, setShowIosHelp] = useState(false);
  const [installed, setInstalled] = useState(false);
  const [ios, setIos] = useState(false);

  useEffect(() => {
    if (isStandalone()) {
      setInstalled(true);
      return;
    }
    setIos(isIos());

    const onBeforeInstall = (event: Event) => {
      event.preventDefault();
      setInstallEvent(event as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setInstallEvent(null);
      setShowIosHelp(false);
    };

    window.addEventListener("beforeinstallprompt", onBeforeInstall);
    window.addEventListener("appinstalled", onInstalled);
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstall);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  if (installed) return null;

  // iOS Safari does not expose beforeinstallprompt: show the native steps.
  if (!installEvent && !ios) return null;

  async function install() {
    if (!installEvent) return;
    await installEvent.prompt();
    const choice = await installEvent.userChoice;
    if (choice.outcome === "accepted") setInstalled(true);
    setInstallEvent(null);
  }

  return (
    <>
      <button
        type="button"
        onClick={installEvent ? install : () => setShowIosHelp(true)}
        className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] right-4 z-40 inline-flex min-h-11 items-center gap-2 rounded-full bg-msb-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-msb-900/20 transition hover:bg-msb-700 active:scale-[0.98]"
        aria-label="Установить MSB на устройство"
      >
        <span aria-hidden="true">⬇</span>
        Установить MSB
      </button>

      {showIosHelp && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/35 p-4 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="install-help-title"
            className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-2xl ring-1 ring-slate-200"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="install-help-title" className="text-base font-bold text-slate-900">
                  Установка MSB
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  В Safari нажмите «Поделиться», затем «На экран Домой».
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowIosHelp(false)}
                className="msb-btn-ghost shrink-0 p-2 text-slate-500"
                aria-label="Закрыть"
              >
                ×
              </button>
            </div>
            <ol className="mt-4 space-y-3 text-sm text-slate-700">
              <li className="flex gap-3"><b className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-msb-100 text-msb-700">1</b><span>Нажмите кнопку «Поделиться» в Safari.</span></li>
              <li className="flex gap-3"><b className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-msb-100 text-msb-700">2</b><span>Выберите «На экран Домой».</span></li>
              <li className="flex gap-3"><b className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-msb-100 text-msb-700">3</b><span>Подтвердите кнопкой «Добавить».</span></li>
            </ol>
          </div>
        </div>
      )}
    </>
  );
}
