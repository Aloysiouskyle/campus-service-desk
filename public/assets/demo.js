"use strict";

(() => {
  const get = (id) => document.getElementById(id);
  const seed = JSON.parse(get("demo-seed").textContent);
  const transitions = JSON.parse(get("demo-transitions").textContent);
  const storageKey = "campus-desk.private-demo.v1";
  const views = ["queue", "new", "detail"];
  const reference = (id) => "CSD-" + String(id).padStart(4, "0");
  let tickets = seed;
  let selected;
  let storage;
  function announce(text) {
    const message = get("demo-message");
    message.textContent = text;
    message.classList.toggle("notice", Boolean(text));
  }

  try {
    storage = window.sessionStorage;
    const saved = storage.getItem(storageKey);
    if (saved) tickets = JSON.parse(saved);
  } catch {
    announce("Browser storage is unavailable or unreadable. Allow session storage to save changes.");
  }

  function save(next) {
    try {
      storage.setItem(storageKey, JSON.stringify(next));
      tickets = next;
      return true;
    } catch {
      announce("Your browser could not save this change. Check available storage and try again.");
      return false;
    }
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function statusPill(status) {
    return element("span", status, "pill " + status.toLowerCase().replaceAll(" ", "-"));
  }

  function renderQueue() {
    const query = get("demo-search").value.trim().toLowerCase();
    const list = get("demo-list");
    list.replaceChildren();
    for (const ticket of tickets) {
      if (!(reference(ticket.id) + " " + ticket.title).toLowerCase().includes(query)) continue;
      const link = document.createElement("a");
      link.href = "#ticket-" + ticket.id;
      const heading = element("div", "");
      heading.append(element("strong", ticket.title), element("small", reference(ticket.id) + " · " + ticket.category));
      link.append(heading, statusPill(ticket.status));
      const row = document.createElement("li");
      row.append(link);
      list.append(row);
    }
    if (!list.children.length) list.append(element("li", "No matching requests."));
  }

  function renderDetail(ticket) {
    get("demo-title").textContent = ticket.title;
    get("demo-reference").textContent = reference(ticket.id);
    get("demo-meta").textContent = ticket.category + " · " + ticket.priority + " priority";
    get("demo-description").textContent = ticket.description;
    get("demo-current").replaceChildren(statusPill(ticket.status));
    get("demo-update").reset();
    get("demo-status").replaceChildren(new Option("Choose a status", ""),
      ...transitions[ticket.status].map((status) => new Option(status)));
    get("demo-history").replaceChildren(...ticket.history.map((event) => {
      const item = document.createElement("li");
      const time = element("time", new Date(event.created_at).toLocaleString());
      time.dateTime = event.created_at;
      item.append(statusPill(event.status), time, element("p", event.note));
      return item;
    }));
  }

  function render() {
    const hash = location.hash.slice(1);
    selected = tickets.find((ticket) => "ticket-" + ticket.id === hash);
    const view = selected ? "detail" : hash === "new" ? "new" : "queue";
    for (const name of views) get("demo-" + name).hidden = name !== view;
    if (selected) renderDetail(selected);
    else if (view === "queue") renderQueue();
  }

  get("demo-search").addEventListener("input", renderQueue);
  get("demo-submit").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    const title = data.title.trim();
    const description = data.description.trim();
    if (title.length < 5 || description.length < 10) {
      announce("Enter a title of at least 5 characters and a description of at least 10.");
      return;
    }
    const id = Math.max(0, ...tickets.map((ticket) => ticket.id)) + 1;
    const created_at = new Date().toISOString();
    const entry = { status: "Open", note: "Request submitted.", created_at };
    const ticket = { ...data, id, title, description, status: "Open", created_at, history: [entry] };
    if (!save([ticket, ...tickets])) return;
    form.reset();
    get("description").dispatchEvent(new Event("input"));
    get("demo-search").value = "";
    announce(reference(id) + " submitted.");
    location.hash = "ticket-" + id;
  });
  get("demo-update").addEventListener("submit", (event) => {
    event.preventDefault();
    const status = get("demo-status").value;
    if (!selected || !transitions[selected.status].includes(status)) return;
    const entry = { status, note: get("demo-note").value.trim() || "Status updated.", created_at: new Date().toISOString() };
    const updated = { ...selected, status, history: [entry, ...selected.history] };
    if (!save(tickets.map((ticket) => ticket.id === selected.id ? updated : ticket))) return;
    announce(reference(selected.id) + " moved to " + status + ".");
    render();
  });
  get("demo-reset").addEventListener("click", () => {
    if (!window.confirm("Discard your demo changes and restore the sample requests?")) return;
    if (!save(seed)) return;
    get("demo-search").value = "";
    get("demo-submit").reset();
    render();
    announce("Sample requests restored.");
  });
  window.addEventListener("hashchange", render);
  render();
})();
