"use strict";

document.querySelectorAll("[data-count-for]").forEach((counter) => {
  const field = document.getElementById(counter.dataset.countFor);
  const update = () => {
    counter.textContent = `${field.value.length} / ${field.maxLength}`;
  };
  field.addEventListener("input", update);
  update();
});

const copy = document.querySelector("[data-copy]");
if (copy && navigator.clipboard) {
  copy.hidden = false;
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(copy.dataset.copy);
      copy.textContent = "Reference copied";
    } catch {
      copy.textContent = "Copy unavailable";
    }
  });
}
