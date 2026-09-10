(() => {
  "use strict";

  const layer = document.createElement("div");
  layer.className = "rpop-layer";
  document.body.appendChild(layer);

  const scrim = document.createElement("div");
  scrim.className = "rpop-scrim";
  layer.appendChild(scrim);

  const closeAll = () => {
    layer.querySelectorAll(".rpop.is-open").forEach((pop) => {
      pop.classList.remove("is-open");
      const homeId = pop.getAttribute("data-home");
      const home = homeId && document.getElementById(homeId);
      if (home) home.appendChild(pop);
    });
    document.querySelectorAll("[data-pop][aria-expanded='true']").forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });
    scrim.classList.remove("is-on");
  };

  const place = (btn, pop) => {
    const home = btn.closest(".rpop-cell") || btn.parentElement;
    if (home && home.id) pop.setAttribute("data-home", home.id);
    layer.appendChild(pop);
    pop.classList.add("is-open");
    btn.setAttribute("aria-expanded", "true");
    scrim.classList.add("is-on");

    const rect = btn.getBoundingClientRect();
    const width = Math.min(280, window.innerWidth - 16);
    pop.style.width = width + "px";
    pop.style.maxHeight = Math.min(360, window.innerHeight - 16) + "px";

    let left = rect.right - width;
    left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
    pop.style.left = left + "px";
    pop.style.top = rect.bottom + 8 + "px";

    const box = pop.getBoundingClientRect();
    if (box.bottom > window.innerHeight - 8) {
      pop.style.top = Math.max(8, rect.top - box.height - 8) + "px";
    }
    if (box.right > window.innerWidth - 8) {
      pop.style.left = Math.max(8, window.innerWidth - width - 8) + "px";
    }
  };

  document.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-pop]");
    if (btn) {
      event.preventDefault();
      event.stopPropagation();
      const pop = document.getElementById(btn.getAttribute("data-pop"));
      if (!pop) return;
      if (pop.classList.contains("is-open")) {
        closeAll();
        return;
      }
      closeAll();
      place(btn, pop);
      return;
    }
    if (event.target === scrim) {
      closeAll();
      return;
    }
    if (!event.target.closest(".rpop")) closeAll();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAll();
  });
  window.addEventListener("resize", closeAll);

  document.addEventListener("change", (event) => {
    const all = event.target.getAttribute && event.target.getAttribute("data-check-all");
    if (!all) return;
    document.querySelectorAll("input[name=ids][form=" + all + "]").forEach((box) => {
      box.checked = event.target.checked;
    });
  });
})();
