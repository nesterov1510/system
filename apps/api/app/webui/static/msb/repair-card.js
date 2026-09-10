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
})();
