"use client";

// Поле «Марка + Модель + Серийный номер» в одну строку.
// Три сегмента разделяются ДВУМЯ ТОЧКАМИ подряд: «Марка..Модель..Серийный номер».
// Раньше разделителем был двойной пробел, но на телефонах автокорректор
// подменяет два пробела на «. » (точка+пробел), что ломало разбиение —
// поэтому разделитель теперь «..», который автокоррекция не трогает.
// Каждый разделитель подсвечивается зелёным прямо в поле — так видно, что
// всё введено правильно. Текст автоматически приводится к ЗАГЛАВНЫМ буквам
// (марка, модель, серийный номер печатаются в бланке заглавными).
import { useCallback, useEffect, useRef } from "react";

/** Привести текст к ЗАГЛАВНЫМ буквам (марка/модель/серийный номер — капсом). */
export function capitalizeWords(s: string): string {
  return s.toUpperCase();
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Разделитель сегментов: ровно две (и более) точки подряд, без пробелов.
const SEGMENT_SEPARATOR = /\.{2,}/g;

function buildHighlightedHtml(text: string): string {
  if (!text) return "";
  const escaped = escapeHtml(text);
  return escaped.replace(SEGMENT_SEPARATOR, (m) => `<span class="msb-devicefield-sep">${m}</span>`);
}

/** Разбить объединённый текст на марку / модель / серийный номер по «..». */
export function splitDeviceCombined(raw: string): {
  brand: string;
  model: string;
  serial: string;
} {
  const parts = (raw || "").split(SEGMENT_SEPARATOR).map((p) => p.trim());
  return {
    brand: parts[0] || "",
    model: parts[1] || "",
    serial: parts.slice(2).join("..").trim(),
  };
}

/** Собрать объединённый текст из марки / модели / серийного номера. */
export function joinDeviceCombined(brand: string, model: string, serial: string): string {
  return [brand, model, serial].filter((p) => p).join("..");
}


function getCaretOffset(el: HTMLElement): number {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return 0;
  const range = sel.getRangeAt(0);
  if (!el.contains(range.startContainer)) return (el.textContent || "").length;
  const preRange = range.cloneRange();
  preRange.selectNodeContents(el);
  preRange.setEnd(range.endContainer, range.endOffset);
  return preRange.toString().length;
}

function setCaretOffset(el: HTMLElement, offset: number) {
  const sel = window.getSelection();
  if (!sel) return;
  const range = document.createRange();
  let remaining = offset;
  let target: Node | null = null;
  let targetOffset = 0;

  const walk = (n: Node): boolean => {
    if (n.nodeType === Node.TEXT_NODE) {
      const len = n.textContent?.length || 0;
      if (remaining <= len) {
        target = n;
        targetOffset = remaining;
        return true;
      }
      remaining -= len;
      return false;
    }
    for (const child of Array.from(n.childNodes)) {
      if (walk(child)) return true;
    }
    return false;
  };
  walk(el);

  if (target) {
    range.setStart(target, targetOffset);
  } else {
    range.selectNodeContents(el);
    range.collapse(false);
  }
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

export default function DeviceCombinedField({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const composing = useRef(false);

  // Синхронизация внешнего значения (например, сброс формы) без поломки курсора.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if ((el.textContent || "") === value) return;
    el.innerHTML = buildHighlightedHtml(value);
  }, [value]);

  const handleInput = useCallback(() => {
    const el = ref.current;
    if (!el || composing.current) return;
    const raw = el.textContent || "";
    const capitalized = capitalizeWords(raw);
    const caret = getCaretOffset(el);
    el.innerHTML = buildHighlightedHtml(capitalized);
    setCaretOffset(el, caret);
    onChange(capitalized);
  }, [onChange]);

  return (
    <div className="relative">
      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-multiline={false}
        onInput={handleInput}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={() => {
          composing.current = false;
          handleInput();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.preventDefault();
        }}
        onPaste={(e) => {
          e.preventDefault();
          const text = e.clipboardData.getData("text/plain").replace(/\n+/g, " ");
          document.execCommand("insertText", false, text);
        }}
        className={
          className ??
          "msb-input min-h-[44px] whitespace-pre-wrap break-words leading-relaxed"
        }
      />
      {!value && placeholder && (
        <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm text-slate-400">
          {placeholder}
        </span>
      )}
    </div>
  );
}
