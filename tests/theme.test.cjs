const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../public/assets/theme.js"), "utf8");

function loadTheme({ dark = false, storage = new Map(), blocked = false } = {}) {
  const events = {};
  const dataset = {};
  const system = { matches: dark, addEventListener: (_, fn) => { events.system = fn; } };
  const toggle = {
    setAttribute: (_, value) => { toggle.pressed = value; },
    addEventListener: (_, fn) => { events.click = fn; },
  };
  const meta = {};
  vm.runInNewContext(source, {
    document: {
      documentElement: { dataset }, querySelector: (q) => q.startsWith("meta") ? meta : toggle,
      addEventListener: (_, fn) => { events.ready = fn; },
    },
    window: { matchMedia: () => system, addEventListener: (_, fn) => { events.storage = fn; } },
    localStorage: {
      getItem: (k) => { if (blocked) throw Error(); return storage.get(k); },
      setItem: (k, v) => { if (blocked) throw Error(); storage.set(k, v); },
    },
  });
  events.ready();
  return { events, dataset, system, toggle };
}

test("device preference follows changes until the user chooses a theme", () => {
  const storage = new Map();
  const page = loadTheme({ storage });
  assert.equal(page.dataset.theme, "light");
  page.system.matches = true;
  page.events.system();
  assert.equal(page.toggle.pressed, "true");
  page.events.click();
  page.events.system();
  assert.equal(page.dataset.theme, "light");
  assert.equal(loadTheme({ dark: true, storage }).dataset.theme, "light");
});

test("cross-tab changes and clearing the saved choice update the switch", () => {
  const page = loadTheme();
  page.events.storage({ key: "campus-desk-theme", newValue: "dark" });
  assert.equal(page.toggle.pressed, "true");
  page.events.storage({ key: null, newValue: null });
  assert.equal(page.toggle.pressed, "false");
});

test("the switch works on the current page when storage is blocked", () => {
  const page = loadTheme({ blocked: true });
  page.events.click();
  assert.equal(page.dataset.theme, "dark");
  assert.equal(page.toggle.hidden, false);
});
