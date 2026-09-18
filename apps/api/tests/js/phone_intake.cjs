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
const blur = (input) => input.dispatchEvent(new window.Event("blur", { bubbles: false }));
const submitForm = () => {
  const ev = new window.Event("submit", { bubbles: true, cancelable: true });
  form.dispatchEvent(ev);
  return ev.defaultPrevented;
};
const warnOf = (input) => {
  const anchor = input.closest(".tv-phone-row") || input;
  return anchor.parentElement.querySelector("[data-phone-warn]");
};
// Сколько вообще блоков-предупреждений на всё поле (регресс: их плодилось по
// одному на каждое нажатие клавиши, и старые не гасли).
const warnCount = (input) => {
  const anchor = input.closest(".tv-phone-row") || input;
  return anchor.parentElement.querySelectorAll("[data-phone-warn]").length;
};

const out = {};
const tick = () => new Promise((r) => setTimeout(r, 0));

(async () => {
  // 1. Префикс уже в поле.
  out.prefilled = phone.value === "+993";

  // 2. Пока номер просто недописан, предупреждение не мелькает.
  type(phone, "+9936");
  type(phone, "+99361");
  type(phone, "+99361234");
  out.typingQuiet = { shown: !warnOf(phone).hidden, count: warnCount(phone) };

  // 3. Чужой код оператора виден сразу.
  type(phone, "+99366123456");
  out.badCode = {
    shown: !warnOf(phone).hidden,
    text: warnOf(phone).textContent,
    badClass: phone.classList.contains("is-bad"),
    ariaInvalid: phone.getAttribute("aria-invalid"),
    count: warnCount(phone),
  };

  // 4. Лишние цифры — тоже сразу.
  type(phone, "+993612345678");
  out.tooLong = { shown: !warnOf(phone).hidden, text: warnOf(phone).textContent };

  // 5. Исправили номер — предупреждение пропало, новых блоков не появилось.
  type(phone, "+99361234567");
  out.valid = {
    hidden: warnOf(phone).hidden,
    text: warnOf(phone).textContent,
    goodClass: phone.classList.contains("is-good"),
    badClassGone: !phone.classList.contains("is-bad"),
    count: warnCount(phone),
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

  // 7. Недописанный номер ловится, когда поле покидают.
  type(phone, "+993612");
  blur(phone);
  out.shortOnBlur = { shown: !warnOf(phone).hidden, text: warnOf(phone).textContent };
  type(phone, "+99361234567");
  out.hiddenAgainAfterFix = warnOf(phone).hidden && warnCount(phone) === 1;

  // 8. +993 не стирается Backspace'ом на границе префикса.
  phone.setSelectionRange(4, 4);
  const ev = new window.KeyboardEvent("keydown", { key: "Backspace", bubbles: true, cancelable: true });
  phone.dispatchEvent(ev);
  out.prefixProtected = ev.defaultPrevented === true;
  phone.setSelectionRange(7, 7);
  const ev2 = new window.KeyboardEvent("keydown", { key: "Backspace", bubbles: true, cancelable: true });
  phone.dispatchEvent(ev2);
  out.deletableAfterPrefix = ev2.defaultPrevented === false;

  // 9. Отправка формы.
  type(phone, "+99366123456");
  out.submitBlockedOnBad = submitForm() === true;
  type(phone, "+993");
  out.submitBlockedOnEmpty = submitForm() === true;
  type(phone, "+99361234567");
  out.submitAllowedOnGood = submitForm() === false;

  // 10. Необязательное поле второго контакта: пустое — не ругаемся.
  out.optionalEmptyOk = (() => {
    if (!second) return null;
    second.dispatchEvent(new window.Event("focus", { bubbles: false }));
    const filled = second.value;
    return { prefillOnFocus: filled === "+993", submitNotBlocked: submitForm() === false };
  })();

  // 11. Дополнительный номер, созданный на лету, тоже проверяется.
  const extra = doc.createElement("input");
  extra.type = "tel";
  extra.name = "customer_phone_extra[]";
  doc.querySelector("[data-extra-phones]").appendChild(extra);
  await tick();
  extra.dispatchEvent(new window.Event("focus", { bubbles: false }));
  type(extra, "+99311123456");
  type(extra, "+9931112345");
  type(extra, "+993111234567");
  out.extraPhone = {
    initialized: extra.dataset.tmPhoneReady === "1",
    warned: (() => {
      const w = extra.parentElement.querySelector("[data-phone-warn]");
      return w ? !w.hidden : false;
    })(),
    count: extra.parentElement.querySelectorAll("[data-phone-warn]").length,
  };

  console.log(JSON.stringify(out));
})();
