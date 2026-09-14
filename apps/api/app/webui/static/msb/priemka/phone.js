// Номер телефона на приёмке.
//
// Требование: номер начинается с +993, дальше код оператора
// (12, 60, 61, 62, 63, 64, 65, 71, 72) и ровно 6 цифр. Префикс +993 уже стоит
// в поле и не стирается, а при ошибке заполняющему показывается подсказка,
// что именно набрать. Форма приёмки помечена novalidate, поэтому отправку
// блокируем сами.
(() => {
  "use strict";
  const PREFIX = "+993";
  const CODES = ["12", "60", "61", "62", "63", "64", "65", "71", "72"];
  const CODE_LIST = CODES.join(", ");
  const form = document.querySelector("[data-tv-intake-form]");
  if (!form) return;

  const digitsOf = (value) => (value || "").replace(/\D/g, "");

  // Проверка номера. Возвращает {ok:true} или {ok:false, msg:"…"}.
  const check = (value) => {
    const digits = digitsOf(value);
    if (!digits) return { ok: false, msg: "Введите номер телефона" };
    if (!digits.startsWith("993")) {
      return { ok: false, msg: `Номер должен начинаться с ${PREFIX}` };
    }
    const body = digits.slice(3);
    if (body.length < 2) {
      return { ok: false, msg: `Введите код оператора: ${CODE_LIST}` };
    }
    const code = body.slice(0, 2);
    if (!CODES.includes(code)) {
      return { ok: false, msg: `Неверный код оператора «${code}». Допустимые коды: ${CODE_LIST}` };
    }
    const rest = body.slice(2);
    if (rest.length < 6) {
      return { ok: false, msg: `После кода оператора нужно ещё ${6 - rest.length} цифр(ы) — всего 6 цифр` };
    }
    if (rest.length > 6) {
      return { ok: false, msg: `После кода оператора должно быть ровно 6 цифр, а введено ${rest.length}` };
    }
    return { ok: true, msg: "" };
  };

  // Необязательное поле, куда никто ничего не вписал (или только +993).
  const isEmptyish = (input) => {
    if (input.required) return false;
    const rest = digitsOf(input.value).replace(/^993/, "");
    return rest === "";
  };

  const warnOf = (input) => {
    let warn = input.parentElement && input.parentElement.querySelector(":scope > [data-phone-warn]");
    if (!warn) {
      warn = document.createElement("p");
      warn.className = "tm-phone-warn";
      warn.setAttribute("data-phone-warn", "");
      warn.setAttribute("role", "alert");
      warn.hidden = true;
      // После самого поля, а не после строки с кнопкой телефонной книги.
      (input.closest(".tv-phone-row") || input).insertAdjacentElement("afterend", warn);
    }
    return warn;
  };

  const paint = (input, result) => {
    const warn = warnOf(input);
    input.classList.toggle("is-bad", !result.ok);
    input.classList.toggle("is-good", result.ok);
    input.setAttribute("aria-invalid", result.ok ? "false" : "true");
    warn.textContent = result.ok ? "" : `⚠ ${result.msg}`;
    warn.hidden = result.ok;
  };

  const validate = (input, force) => {
    if (isEmptyish(input) && !force) {
      input.classList.remove("is-bad", "is-good");
      input.removeAttribute("aria-invalid");
      const warn = warnOf(input);
      warn.hidden = true;
      warn.textContent = "";
      return { ok: true, msg: "" };
    }
    const result = check(input.value);
    paint(input, result);
    return result;
  };

  const keepPrefix = (input) => {
    if (input.value.startsWith(PREFIX)) return;
    // Префикс затёрли (выделили всё и напечатали номер) — возвращаем его
    // и оставляем то, что набрано после.
    const typed = input.value.replace(/^\+/, "").replace(/^993/, "");
    input.value = PREFIX + typed;
  };

  const init = (input) => {
    if (input.dataset.tmPhoneReady === "1") return;
    input.dataset.tmPhoneReady = "1";
    input.setAttribute("data-tm-phone", "");
    input.maxLength = 20;
    if (input.required && !input.value.trim()) input.value = PREFIX;

    input.addEventListener("keydown", (e) => {
      if (e.key !== "Backspace") return;
      const pos = input.selectionStart == null ? input.value.length : input.selectionStart;
      const end = input.selectionEnd == null ? pos : input.selectionEnd;
      // Не даём стереть +993.
      if (pos <= PREFIX.length && end <= PREFIX.length) e.preventDefault();
    });

    input.addEventListener("input", () => {
      keepPrefix(input);
      validate(input, false);
    });

    // В необязательное поле префикс подставляем при первом касании.
    input.addEventListener("focus", () => {
      if (!input.value.trim()) input.value = PREFIX;
    });

    input.addEventListener("blur", () => validate(input, false));
  };

  const fields = () =>
    Array.from(form.querySelectorAll('input[type="tel"]')).filter(
      (el) => el.type === "tel"
    );

  fields().forEach(init);

  // Дополнительные номера создаются на лету (televisions.js) — подхватываем.
  const observer = new MutationObserver(() => fields().forEach(init));
  observer.observe(form, { childList: true, subtree: true });

  form.addEventListener("submit", (e) => {
    let bad = null;
    fields().forEach((input) => {
      const result = validate(input, input.required);
      if (!result.ok && !bad) bad = input;
    });
    if (bad) {
      e.preventDefault();
      bad.focus();
    }
  });
})();
