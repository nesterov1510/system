// Прогон настоящего static/msb/priemka/phone.js в jsdom: проверка номера
// телефона на приёмке (+993 + код оператора + 6 цифр).
// Запускается из tests/test_phone_intake.py. Без jsdom — SKIP.
const fs = require("fs");

let JSDOM;
try {
  JSDOM = require("jsdom").JSDOM;
} catch (err) {
  console.log(JSON.stringify({ skip: "jsdom not installed" }));
  process.exit(0);
}

const [htmlFile, jsFile] = process.argv.slice(2);
const dom = new JSDOM(fs.readFileSync(htmlFile, "utf8"), {
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;
window.eval(fs.readFileSync(jsFile, "utf8"));

const doc = window.document;
const form = doc.querySelector("[data-tv-intake-form]");
const phone = doc.querySelector("#tvCustomerPhone");
const second = doc.querySelector("#tvSecondPhone");

const type = (input, value) => {
  input.value = value;
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
};
const warnOf = (input) =>
  (input.closest(".tv-phone-row") || input).parentElement.querySelector("[data-phone-warn]");

const out = {};
const tick = () => new Promise((r) => setTimeout(r, 0));

(async () => {
  // 1. Префикс уже в поле.
  out.prefilled = phone.value === "+993";

  // 2. Неверный код оператора — предупреждение.
  type(phone, "+99366123456");
  out.badCode = {
    shown: warnOf(phone) && !warnOf(phone).hidden,
    text: warnOf(phone) ? warnOf(phone).textContent : "",
    badClass: phone.classList.contains("is-bad"),
    ariaInvalid: phone.getAttribute("aria-invalid"),
  };

  // 3. Мало цифр после кода.
  type(phone, "+99361234");
  out.tooShort = { shown: !warnOf(phone).hidden, text: warnOf(phone).textContent };

  // 4. Лишние цифры.
  type(phone, "+993612345678");
  out.tooLong = { shown: !warnOf(phone).hidden, text: warnOf(phone).textContent };

  // 5. Верный номер — предупреждение снято.
  type(phone, "+99361234567");
  out.valid = {
    hidden: warnOf(phone).hidden,
    goodClass: phone.classList.contains("is-good"),
    badClassGone: !phone.classList.contains("is-bad"),
  };

  // 6. Все допустимые коды проходят, чужие — нет.
  out.codes = {};
  ["12", "60", "61", "62", "63", "64", "65", "71", "72"].forEach((c) => {
    type(phone, `+993${c}123456`);
    out.codes[c] = warnOf(phone).hidden;
  });
  ["11", "66", "70", "73", "99"].forEach((c) => {
    type(phone, `+993${c}123456`);
    out.codes["bad" + c] = warnOf(phone).hidden;
  });

  // 7. +993 не стирается Backspace'ом на границе префикса.
  type(phone, "+99361234567");
  phone.setSelectionRange(4, 4);
  const ev = new window.KeyboardEvent("keydown", { key: "Backspace", bubbles: true, cancelable: true });
  phone.dispatchEvent(ev);
  out.prefixProtected = ev.defaultPrevented === true;
  // а после префикса стирать можно
  phone.setSelectionRange(7, 7);
  const ev2 = new window.KeyboardEvent("keydown", { key: "Backspace", bubbles: true, cancelable: true });
  phone.dispatchEvent(ev2);
  out.deletableAfterPrefix = ev2.defaultPrevented === false;

  // 8. Отправку формы с неверным номером скрипт блокирует.
  type(phone, "+99366123456");
  const submit = new window.Event("submit", { bubbles: true, cancelable: true });
  form.dispatchEvent(submit);
  out.submitBlockedOnBad = submit.defaultPrevented === true;
  type(phone, "+99361234567");
  const submit2 = new window.Event("submit", { bubbles: true, cancelable: true });
  form.dispatchEvent(submit2);
  out.submitAllowedOnGood = submit2.defaultPrevented === false;

  // 9. Необязательное поле второго контакта: пустое — не ругаемся.
  out.optionalEmptyOk = (() => {
    if (!second) return null;
    second.dispatchEvent(new window.Event("focus", { bubbles: false }));
    const filled = second.value;
    const submit3 = new window.Event("submit", { bubbles: true, cancelable: true });
    form.dispatchEvent(submit3);
    return { prefillOnFocus: filled === "+993", submitNotBlocked: submit3.defaultPrevented === false };
  })();

  // 10. Дополнительный номер, созданный на лету, тоже проверяется.
  const extra = doc.createElement("input");
  extra.type = "tel";
  extra.name = "customer_phone_extra[]";
  doc.querySelector("[data-extra-phones]").appendChild(extra);
  await tick();
  extra.dispatchEvent(new window.Event("focus", { bubbles: false }));
  type(extra, "+99311123456");
  out.extraPhone = {
    initialized: extra.dataset.tmPhoneReady === "1",
    prefill: "+993",
    warned: (() => {
      const w = extra.parentElement.querySelector("[data-phone-warn]");
      return w ? !w.hidden : false;
    })(),
  };

  console.log(JSON.stringify(out));
})();
