"""Browser modal for collecting and reviewing multiple AI guidance responses."""

from __future__ import annotations


def render_guidance_modal(has_saved_responses: bool) -> str:
    """Render the response-review dialog and its non-blocking controller."""
    switch_button = (
        '<button id="switch-guidance-button" class="secondary-action" type="button">'
        "Review or switch saved AI response</button>"
        if has_saved_responses
        else ""
    )
    return switch_button + r'''
<dialog id="guidance-dialog" class="guidance-dialog">
  <div class="dialog-heading">
    <div><h2>AI rate guidance review</h2><p>Compare validated responses before choosing one.</p></div>
    <button id="close-guidance-dialog" type="button" aria-label="Close">×</button>
  </div>
  <div id="guidance-progress" class="guidance-progress" role="status">Processing requests. Please be patient…</div>
  <div id="guidance-response-grid" class="guidance-response-grid"></div>
  <p id="guidance-round-message" class="guidance-round-message"></p>
</dialog>
<script>
(() => {
  const form = document.getElementById("guidance-form");
  const openButton = document.getElementById("guidance-button");
  const switchButton = document.getElementById("switch-guidance-button");
  const dialog = document.getElementById("guidance-dialog");
  const closeButton = document.getElementById("close-guidance-dialog");
  const progress = document.getElementById("guidance-progress");
  const grid = document.getElementById("guidance-response-grid");
  const roundMessage = document.getElementById("guidance-round-message");
  if (!form || !openButton || !dialog) return;

  let responses = [];
  let attempts = 0;
  let attemptLimit = 5;
  let processing = false;
  let errors = [];
  let controller = null;
  let runId = 0;

  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  };

  const post = async (path, extra = {}, signal) => {
    const data = new URLSearchParams(new FormData(form));
    for (const [key, value] of Object.entries(extra)) data.set(key, value);
    const result = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: data,
      signal,
    });
    const payload = await result.json();
    if (!result.ok) throw new Error(payload.error || `Request failed (${result.status})`);
    return payload;
  };

  const dashboardUrl = () => `/dashboard?${new URLSearchParams(new FormData(form))}`;

  const money = (value) => new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
  }).format(Number(value || 0));

  const renderBreakdown = (response, type, label) => {
    const section = element("section", undefined, "guidance-breakdown");
    section.append(element("h4", label));
    const table = element("table", undefined, "guidance-rate-table");
    const head = element("thead");
    const headRow = element("tr");
    ["Upper bracket", "Rate"].forEach((title) => headRow.append(element("th", title)));
    head.append(headRow);
    table.append(head);
    const body = element("tbody");
    const breakdown = (response.breakdowns || []).find((item) => item.type === type);
    for (const bracket of breakdown ? breakdown.brackets || [] : []) {
      const row = element("tr");
      row.append(element("td", bracket.bracket === null ? "Top bracket" : money(bracket.bracket)));
      row.append(element("td", `${bracket.rate}%`));
      body.append(row);
    }
    table.append(body);
    section.append(table);
    return section;
  };

  const abortQueries = () => {
    runId += 1;
    if (controller) controller.abort();
    controller = null;
    processing = false;
  };

  const render = () => {
    grid.replaceChildren();
    responses.forEach((response, index) => {
      const card = element("article", undefined, "guidance-response-card");
      card.append(element("h3", `Response ${index + 1}`));
      card.append(renderBreakdown(response, "federal_ordinary", "Federal ordinary income"));
      card.append(renderBreakdown(response, "federal_long_term", "Federal long-term gains"));
      card.append(renderBreakdown(response, "state", "State income tax"));
      const deduction = response.standard_deduction || {};
      card.append(element(
        "p",
        `Standard deduction: ${money(deduction.amount)} · ${String(deduction.filing_status || "").replaceAll("_", " ")}`,
        "deduction",
      ));
      const actions = element("div", undefined, "response-actions");
      const use = element("button", "Use", "use-response");
      const retry = element("button", "Discard and retry", "discard-response");
      use.type = "button";
      retry.type = "button";
      use.disabled = responses.length === 0;
      // A completed round can still be reviewed and trimmed, even if no retry remains.
      retry.disabled = false;
      use.addEventListener("click", () => choose(index));
      retry.addEventListener("click", () => discard(index));
      actions.append(use, retry);
      card.append(actions);
      grid.append(card);
    });
    for (let index = responses.length; index < 3; index += 1) {
      const placeholder = element("article", undefined, "guidance-response-card placeholder");
      placeholder.append(element("h3", `Response ${index + 1}`));
      placeholder.append(element("p", processing ? "Waiting for a valid response…" : "No valid response available."));
      grid.append(placeholder);
    }
  };

  const finish = (message) => {
    processing = false;
    controller = null;
    progress.classList.remove("processing");
    progress.textContent = message;
    roundMessage.textContent = errors.length ? `Validation/API issues in this round: ${errors.join(" · ")}` : "";
    render();
  };

  const queryUntilComplete = async () => {
    const thisRun = ++runId;
    processing = true;
    progress.classList.add("processing");
    render();
    while (responses.length < 3 && attempts < attemptLimit && thisRun === runId) {
      attempts += 1;
      progress.textContent = `Processing request ${attempts} of ${attemptLimit}. ${responses.length} valid response${responses.length === 1 ? "" : "s"} received. You can use, discard, or close this window while waiting.`;
      controller = new AbortController();
      try {
        const result = await post("/guidance-query", { attempt: String(attempts) }, controller.signal);
        if (thisRun !== runId) return;
        if (result.valid) responses.push(result.response);
        else errors.push(`Attempt ${attempts}: ${result.error}`);
      } catch (error) {
        if (thisRun !== runId || error.name === "AbortError") return;
        errors.push(`Attempt ${attempts}: ${error.message}`);
      }
      render();
    }
    if (thisRun !== runId) return;
    if (responses.length >= 3) finish("Three valid responses are ready. Choose one to use.");
    else finish(`Request round complete after ${attempts} attempt${attempts === 1 ? "" : "s"}. Choose from the ${responses.length} valid response${responses.length === 1 ? "" : "s"} available; no more responses will arrive.`);
  };

  const open = async () => {
    abortQueries();
    const openRun = runId;
    dialog.showModal();
    responses = [];
    attempts = 0;
    attemptLimit = 5;
    errors = [];
    processing = true;
    progress.classList.add("processing");
    progress.textContent = "Checking for saved responses…";
    roundMessage.textContent = "";
    render();
    try {
      const saved = await post("/guidance-saved");
      if (openRun !== runId || !dialog.open) return;
      if (saved.warning) errors.push(saved.warning);
      if (saved.responses.length) {
        responses = saved.responses;
        attemptLimit = Math.max(0, 5 - saved.responses.length);
        finish(`Loaded ${responses.length} saved response${responses.length === 1 ? "" : "s"}. Discard and retry can make up to ${attemptLimit} new request${attemptLimit === 1 ? "" : "s"}.`);
      } else {
        await queryUntilComplete();
      }
    } catch (error) {
      if (openRun !== runId || !dialog.open) return;
      finish(error.message);
    }
  };

  const discard = async (index) => {
    abortQueries();
    responses.splice(index, 1);
    if (attempts >= attemptLimit) {
      finish(`Request round complete after ${attempts} attempt${attempts === 1 ? "" : "s"}. The retry limit has been reached.`);
      return;
    }
    await queryUntilComplete();
  };

  const choose = async (index) => {
    if (!responses[index]) return;
    abortQueries();
    progress.classList.add("processing");
    progress.textContent = "Saving all valid responses and applying your selection…";
    render();
    try {
      await post("/guidance-save", {
        responses: JSON.stringify(responses), selected_index: String(index),
      });
      dialog.close();
      window.location.assign(dashboardUrl());
    } catch (error) {
      finish(error.message);
    }
  };

  openButton.addEventListener("click", open);
  if (switchButton) switchButton.addEventListener("click", open);
  closeButton.addEventListener("click", () => { abortQueries(); dialog.close(); });
  dialog.addEventListener("cancel", () => abortQueries());
})();
</script>'''
