"use strict";

(() => {
  const get = (id) => document.getElementById(id);
  const seed = JSON.parse(get("demo-seed").textContent);
  const transitions = JSON.parse(get("demo-transitions").textContent);
  const storageKey = "campus-desk.private-demo.v1";
  const views = ["queue", "new", "detail", "notifications"];
  const reference = (id) => "CSD-" + String(id).padStart(4, "0");
  const roleKey = "campus-desk.demo-role";
  const demoStaff = "Grace Namuli";
  const roles = document.querySelectorAll('input[name="demo-role"]');
  const studentSamples = new Set([4, 6, 12]);
  const sampleIds = new Set(seed.map((ticket) => ticket.id));
  let role = "student";
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
    if (storage.getItem(roleKey) === "staff") role = "staff";
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

  function visibleToStudent(ticket) {
    // Earlier demos had one user. Keep their submitted tickets in the student view.
    return ticket.submittedBy === "student" ||
      (ticket.submittedBy === undefined && (studentSamples.has(ticket.id) || !sampleIds.has(ticket.id)));
  }

  function visible(ticket) {
    return role === "staff" || visibleToStudent(ticket);
  }

  function renderQueue() {
    get("demo-queue-title").textContent = role === "student" ? "My requests" : "Staff queue";
    get("demo-assignment-filter").hidden = role !== "staff";
    const assignment = role === "staff" ? get("demo-assignment").value : "";
    const query = get("demo-search").value.trim().toLowerCase();
    const list = get("demo-list");
    list.replaceChildren();
    for (const ticket of tickets) {
      if (!visible(ticket)) continue;
      if (assignment === "mine" && ticket.assigneeName !== demoStaff) continue;
      if (assignment === "unassigned" && ticket.assigneeName) continue;
      if (!(reference(ticket.id) + " " + ticket.title).toLowerCase().includes(query)) continue;
      const link = document.createElement("a");
      link.href = "#ticket-" + ticket.id;
      const heading = element("div", "");
      heading.append(element("strong", ticket.title), element("small", reference(ticket.id) + " · " + ticket.category + " · " + (ticket.assigneeName || "Unassigned")));
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
    get("demo-assignee").textContent = ticket.assigneeName || "Unassigned";
    get("demo-claim").hidden = role !== "staff" || Boolean(ticket.assigneeName);
    get("demo-update").hidden = role !== "staff";
    get("demo-update").reset();
    get("demo-status").replaceChildren(new Option("Choose a status", ""),
      ...transitions[ticket.status].map((status) => new Option(status)));
    const messages = (ticket.messages ?? []).map((message) => {
      const item = element("li", "");
      const time = element("time", new Date(message.createdAt).toLocaleString());
      time.dateTime = message.createdAt;
      item.append(element("strong", message.author), time, element("p", message.body));
      return item;
    });
    get("demo-messages").replaceChildren(...(messages.length ? messages : [element("li", "No messages yet.", "muted")]));
    get("demo-message-form").reset();
    get("demo-history").replaceChildren(...ticket.history.map((event) => {
      const item = document.createElement("li");
      const time = element("time", new Date(event.created_at).toLocaleString());
      time.dateTime = event.created_at;
      item.append(statusPill(event.status), time, element("p", event.note));
      return item;
    }));
  }

  function renderNotifications() {
    const items = tickets.filter(visible).flatMap((ticket) =>
      (ticket.notifications ?? []).filter((item) => item.recipient === role)
        .map((item) => ({ ticket, item })));
    items.sort((a, b) => b.item.createdAt.localeCompare(a.item.createdAt));
    const unread = items.filter(({ item }) => !item.read).length;
    get("demo-inbox-link").textContent = "Notifications (" + unread + ")";
    const list = get("demo-notification-list");
    list.replaceChildren();
    for (const { ticket, item } of items) {
      const label = (item.kind === "reply" ? "New reply" : "Status changed") +
        " on " + reference(ticket.id) + " · " + (item.read ? "Read" : "Unread");
      const button = element("button", label, "button outline");
      button.type = "button";
      button.addEventListener("click", () => {
        const notifications = ticket.notifications.map((entry) => entry === item ? { ...entry, read: true } : entry);
        if (!save(tickets.map((entry) => entry.id === ticket.id ? { ...entry, notifications } : entry))) return;
        location.hash = "ticket-" + ticket.id;
        render();
        get(item.kind === "reply" ? "demo-conversation" : "demo-history").scrollIntoView();
      });
      const row = element("li", "");
      row.append(button);
      list.append(row);
    }
    if (!items.length) list.append(element("li", "No notifications yet.", "muted"));
  }

  function withNotification(ticket, recipient, kind) {
    if (!recipient) return ticket;
    const notification = { recipient, kind, createdAt: new Date().toISOString(), read: false };
    return { ...ticket, notifications: [...(ticket.notifications ?? []), notification] };
  }

  function render() {
    const hash = location.hash.slice(1);
    selected = tickets.find((ticket) => visible(ticket) && "ticket-" + ticket.id === hash);
    const view = selected ? "detail" : ["new", "notifications"].includes(hash) ? hash : "queue";
    renderNotifications();
    for (const name of views) get("demo-" + name).hidden = name !== view;
    if (selected) renderDetail(selected);
    else if (view === "queue") renderQueue();
  }

  for (const input of roles) {
    input.checked = input.value === role;
    input.addEventListener("change", () => {
      role = input.value;
      try { storage.setItem(roleKey, role); } catch { /* Switching still works for this page. */ }
      get("demo-search").value = "";
      if (selected && !visible(selected)) location.hash = "queue";
      announce(role === "staff" ? "Staff view. You can manage all demo requests." : "Student view. Showing your requests.");
      render();
    });
  }

  get("demo-assignment").addEventListener("change", renderQueue);
  get("demo-claim").addEventListener("click", () => {
    if (role !== "staff" || !selected || selected.assigneeName) return;
    const entry = { status: selected.status, note: "Assigned to " + demoStaff + ".", created_at: new Date().toISOString() };
    const updated = { ...selected, assigneeName: demoStaff, history: [entry, ...selected.history] };
    if (!save(tickets.map((ticket) => ticket.id === selected.id ? updated : ticket))) return;
    announce(reference(selected.id) + " assigned to " + demoStaff + ".");
    render();
  });
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
    const ticket = { ...data, id, title, description, submittedBy: role, status: "Open", created_at, history: [entry] };
    if (!save([ticket, ...tickets])) return;
    form.reset();
    get("description").dispatchEvent(new Event("input"));
    get("demo-search").value = "";
    announce(reference(id) + " submitted.");
    location.hash = "ticket-" + id;
  });
  get("demo-message-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const body = get("demo-message-body").value.trim();
    if (!selected || !body || body.length > 2000) {
      announce("Enter a message between 1 and 2,000 characters.");
      return;
    }
    const message = {
      author: role === "staff" ? demoStaff + " · Staff" : "Student",
      body,
      createdAt: new Date().toISOString(),
    };
    const recipient = role === "staff"
      ? (visibleToStudent(selected) ? "student" : null)
      : (selected.assigneeName ? "staff" : null);
    const updated = withNotification({ ...selected, messages: [...(selected.messages ?? []), message] }, recipient, "reply");
    if (!save(tickets.map((ticket) => ticket.id === selected.id ? updated : ticket))) return;
    announce("Message sent.");
    render();
    get("demo-message-body").focus();
  });
  get("demo-update").addEventListener("submit", (event) => {
    event.preventDefault();
    const status = get("demo-status").value;
    if (role !== "staff" || !selected || !transitions[selected.status].includes(status)) return;
    const entry = { status, note: get("demo-note").value.trim() || "Status updated.", created_at: new Date().toISOString() };
    const updated = withNotification({ ...selected, status, history: [entry, ...selected.history] },
      visibleToStudent(selected) ? "student" : null, "status");
    if (!save(tickets.map((ticket) => ticket.id === selected.id ? updated : ticket))) return;
    announce(reference(selected.id) + " moved to " + status + ".");
    render();
  });
  get("demo-reset").addEventListener("click", () => {
    if (!window.confirm("Discard your demo changes and restore the sample requests?")) return;
    if (!save(seed)) return;
    get("demo-assignment").value = "";
    get("demo-search").value = "";
    get("demo-submit").reset();
    render();
    announce("Sample requests restored.");
  });
  window.addEventListener("hashchange", render);
  render();
})();
