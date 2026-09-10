window.msbRpopClose = function () {
  document.querySelectorAll(".rpop.is-open").forEach((el) => {
    el.classList.remove("is-open");
    if (el._home) el._home.appendChild(el);
  });
  document.querySelectorAll(".rpop-trigger[aria-expanded='true']").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
  });
  const scrim = document.getElementById("rpop-scrim");
  if (scrim) scrim.classList.remove("is-on");
};

window.msbRpop = function (btn) {
  if (!btn) return false;
  const pop = btn.parentNode && btn.parentNode.querySelector(".rpop");
  if (!pop) return false;

  let scrim = document.getElementById("rpop-scrim");
  if (!scrim) {
    scrim = document.createElement("div");
    scrim.id = "rpop-scrim";
    scrim.className = "rpop-scrim";
    document.body.appendChild(scrim);
    scrim.addEventListener("click", () => window.msbRpopClose());
  }

  if (pop.classList.contains("is-open")) {
    window.msbRpopClose();
    return false;
  }

  window.msbRpopClose();
  pop._home = btn.parentNode;
  document.body.appendChild(pop);
  pop.classList.add("is-open");
  btn.setAttribute("aria-expanded", "true");
  scrim.classList.add("is-on");

  const rect = btn.getBoundingClientRect();
  const width = Math.min(280, window.innerWidth - 16);
  pop.style.position = "fixed";
  pop.style.zIndex = "400";
  pop.style.width = width + "px";
  pop.style.maxHeight = Math.min(360, window.innerHeight - 16) + "px";
  let left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
  pop.style.left = left + "px";
  pop.style.top = rect.bottom + 8 + "px";
  const box = pop.getBoundingClientRect();
  if (box.bottom > window.innerHeight - 8) {
    pop.style.top = Math.max(8, rect.top - box.height - 8) + "px";
  }
  return false;
};

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") window.msbRpopClose();
});

document.addEventListener("change", (event) => {
  const all = event.target.getAttribute && event.target.getAttribute("data-check-all");
  if (!all) return;
  document.querySelectorAll("input[name=ids][form=" + all + "]").forEach((box) => {
    box.checked = event.target.checked;
  });
});
