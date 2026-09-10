(() => {
  "use strict";

  const closeAll = (except) => {
    document.querySelectorAll(".rpop.is-open").forEach((pop) => {
      if (pop === except) return;
      pop.classList.remove("is-open");
      pop.hidden = true;
    });
  };

  const place = (btn, pop) => {
    pop.hidden = false;
    pop.classList.add("is-open");
    const rect = btn.getBoundingClientRect();
    const width = Math.min(260, window.innerWidth - 16);
    let left = Math.min(rect.right - width, window.innerWidth - width - 8);
    left = Math.max(8, left);
    pop.style.position = "fixed";
    pop.style.left = left + "px";
    pop.style.top = rect.bottom + 6 + "px";
    pop.style.width = width + "px";
    const box = pop.getBoundingClientRect();
    if (box.bottom > window.innerHeight - 8) {
      pop.style.top = Math.max(8, rect.top - box.height - 6) + "px";
    }
  };

  document.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-pop]");
    if (btn) {
      event.preventDefault();
      event.stopPropagation();
      const pop = btn.parentElement && btn.parentElement.querySelector(".rpop");
      if (!pop) return;
      if (pop.classList.contains("is-open")) {
        closeAll();
        return;
      }
      closeAll();
      place(btn, pop);
      return;
    }
    if (!event.target.closest(".rpop")) closeAll();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAll();
  });
  window.addEventListener("scroll", () => closeAll(), true);
  window.addEventListener("resize", () => closeAll());

  document.addEventListener("change", (event) => {
    const all = event.target.getAttribute && event.target.getAttribute("data-check-all");
    if (!all) return;
    document.querySelectorAll("input[name=ids][form=" + all + "]").forEach((box) => {
      box.checked = event.target.checked;
    });
  });
})();
