(() => {
  "use strict";

  const openChip = (form) => {
    const view = form.querySelector("[data-ichip-open]");
    const edit = form.querySelector(".ichip-edit");
    if (!view || !edit) return;
    view.hidden = true;
    edit.hidden = false;
    edit.focus();
    if (typeof edit.select === "function") edit.select();
  };

  const closeChip = (form) => {
    const view = form.querySelector("[data-ichip-open]");
    const edit = form.querySelector(".ichip-edit");
    if (!view || !edit) return;
    edit.hidden = true;
    view.hidden = false;
  };

  const currentLabel = (form) => {
    const view = form.querySelector("[data-ichip-open]");
    const text = (view && view.textContent || "").trim();
    return text === "—" ? "" : text;
  };

  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-ichip-open]");
    if (!opener) return;
    const form = opener.closest("[data-ichip]");
    if (form) openChip(form);
  });

  document.addEventListener("focusout", (event) => {
    const form = event.target.closest && event.target.closest("[data-ichip]");
    if (!form || !event.target.classList.contains("ichip-edit")) return;
    window.setTimeout(() => {
      if (form.contains(document.activeElement)) return;
      if (event.target.value.trim() === currentLabel(form)) {
        closeChip(form);
        return;
      }
      form.submit();
    }, 0);
  });

  document.addEventListener("keydown", (event) => {
    const form = event.target.closest && event.target.closest("[data-ichip]");
    if (!form || !event.target.classList.contains("ichip-edit")) return;
    if (event.key === "Enter" && event.target.tagName !== "TEXTAREA") {
      event.preventDefault();
      event.target.blur();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeChip(form);
    }
  });

  document.addEventListener("change", (event) => {
    const form = event.target.closest && event.target.closest("[data-ichip-auto]");
    if (form) form.submit();
  });

  /* ------------------------------------------------------------------ *
   * Окна-списки чипов паспорта (Состояние / Комплектация / Доставка).
   * Открываются двойным кликом по чипу; на сенсорном экране, где двойного
   * клика нет, достаточно одного касания.
   * ------------------------------------------------------------------ */
  const scrim = document.querySelector("[data-pop-scrim]");
  const noHover = window.matchMedia && window.matchMedia("(hover: none)").matches;

  const closePopups = () => {
    document.querySelectorAll("[data-pop-modal]").forEach((modal) => { modal.hidden = true; });
    const menu = document.querySelector("[data-mpop]");
    if (menu) menu.hidden = true;
    if (scrim) scrim.hidden = true;
  };

  const openModal = (selector) => {
    const modal = document.querySelector(selector);
    if (!modal) return;
    closePopups();
    modal.hidden = false;
    if (scrim) scrim.hidden = false;
    const first = modal.querySelector("input:not([type=hidden]), select, textarea");
    if (first) first.focus();
  };

  document.addEventListener("dblclick", (event) => {
    const chip = event.target.closest("[data-popchip]");
    if (!chip) return;
    event.preventDefault();
    openModal(chip.dataset.popchip);
  });

  document.addEventListener("click", (event) => {
    if (!noHover) return;
    const chip = event.target.closest("[data-popchip]");
    if (chip) openModal(chip.dataset.popchip);
  });

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-pop-close]") || event.target.closest("[data-pop-scrim]")) {
      closePopups();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePopups();
  });

  /* ------------------------------------------------------------------ *
   * Меню действий мастера: клик по имени — «передать / назначить
   * мастером / назначить помощником / убрать с ремонта».
   * ------------------------------------------------------------------ */
  const mForm = document.querySelector("[data-mact-form]");
  const mPop = document.querySelector("[data-mpop]");

  if (mForm && mPop) {
    document.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-mchip]");
      if (chip) {
        const kind = chip.dataset.mkind || "";
        mForm.elements.user_id.value = chip.dataset.mchip || "";
        const slot = mPop.querySelector("[data-mname-slot]");
        if (slot) slot.textContent = chip.dataset.mname || "";
        mPop.querySelectorAll("[data-mact]").forEach((btn) => {
          // Убирать нечего, если мастер на ремонте не значится.
          if (btn.dataset.mact === "remove") btn.disabled = !kind;
        });
        mPop.hidden = false;
        const box = chip.getBoundingClientRect();
        const width = mPop.offsetWidth || 240;
        const left = Math.max(10, Math.min(box.left, window.innerWidth - width - 10));
        mPop.style.left = left + "px";
        mPop.style.top = (box.bottom + 6) + "px";
        return;
      }
      const action = event.target.closest("[data-mact]");
      if (action) {
        mForm.elements.action.value = action.dataset.mact;
        mPop.hidden = true;
        mForm.submit();
        return;
      }
      if (!event.target.closest("[data-mpop]")) mPop.hidden = true;
    });
  }
})();
