(() => {
  "use strict";
  const key = "campus-desk-theme";
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  let preference;
  let toggle;

  function valid(value) {
    return value === "light" || value === "dark";
  }

  function apply() {
    const theme = valid(preference) ? preference : (system.matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#111b1b" : "#f7f5ef";
    if (toggle) toggle.setAttribute("aria-pressed", String(theme === "dark"));
  }

  try { preference = localStorage.getItem(key); } catch { /* Storage may be disabled. */ }
  apply();
  system.addEventListener("change", apply);
  window.addEventListener("storage", (event) => {
    if (event.key === key || event.key === null) {
      preference = event.newValue;
      apply();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    toggle = document.querySelector("[data-theme-toggle]");
    if (!toggle) return;
    apply();
    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      preference = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      try { localStorage.setItem(key, preference); } catch { /* Keep the current page usable. */ }
      apply();
    });
  });
})();
