"""Browser modal for collecting and reviewing multiple AI guidance responses."""

from __future__ import annotations


def render_guidance_modal(has_saved_responses: bool) -> str:
    """Render the response-review dialog and its non-blocking controller."""
    switch_button = (
        '<button id="switch-guidance-button" class="secondary-action" type="button" disabled>'
        "No saved AI responses</button>"
    )
    profile_note = (
        '<p id="guidance-profile-note" class="state-guidance-note" hidden></p>'
        if has_saved_responses
        else ""
    )
    return switch_button + profile_note + r'''
<dialog id="guidance-dialog" class="guidance-dialog">
  <div class="dialog-heading">
    <div><h2>AI rate guidance review</h2><p>Review and edit bracket schedules before choosing one to use.</p></div>
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
  const provider = document.getElementById("ai-provider");
  const profileNote = document.getElementById("guidance-profile-note");
  const profileInputs = [
    document.getElementById("state-residence"),
    document.getElementById("filing-status"),
    document.getElementById("dependent-count"),
    provider,
  ].filter(Boolean);
  if (!form || !openButton || !dialog) return;

  let responses = [];
  let attempts = 0;
  let attemptLimit = 5;
  let processing = false;
  let errors = [];
  let controller = null;
  let runId = 0;
  let profileRevision = 0;

  const providerLabels = {
    openai: "ChatGPT / OpenAI API",
    gemini: "Google Gemini API",
    openrouter: "OpenRouter API",
  };

  const activeProviderLabel = () => providerLabels[provider?.value] || "AI";
  const activeProfileKey = () => JSON.stringify({
    state: document.getElementById("state-residence")?.value || "",
    filingStatus: document.getElementById("filing-status")?.value || "",
    dependents: document.getElementById("dependent-count")?.value || "0",
    provider: provider?.value || "",
  });
  const initialProfileKey = activeProfileKey();

  const syncProfileControls = async () => {
    const revision = ++profileRevision;
    const state = document.getElementById("state-residence");
    const profileFields = [
      ["state-residence", "guidance-state"],
      ["filing-status", "guidance-filing-status"],
      ["dependent-count", "guidance-dependent-count"],
      ["ordinary-income", "guidance-ordinary-income"],
    ];
    profileFields.forEach(([sourceId, targetId]) => {
      const source = document.getElementById(sourceId);
      const target = document.getElementById(targetId);
      if (source && target) target.value = source.value;
    });
    const hasState = Boolean(state?.value);
    if (profileNote) {
      const changed = activeProfileKey() !== initialProfileKey;
      profileNote.hidden = !changed;
      profileNote.textContent = changed
        ? "Tax profile changed. Review matching saved guidance or request new guidance before relying on the displayed estimate."
        : "";
    }
    openButton.textContent = `Get ${activeProviderLabel()} rate guidance`;
    openButton.disabled = !hasState;
    if (!switchButton) return;
    if (!hasState) {
      switchButton.disabled = true;
      switchButton.textContent = "Select a state to review saved guidance";
      return;
    }
    switchButton.disabled = true;
    switchButton.textContent = `Checking saved ${activeProviderLabel()} responses…`;
    try {
      const saved = await post("/guidance-saved");
      if (revision !== profileRevision) return;
      const count = saved.responses?.length || 0;
      switchButton.disabled = count === 0;
      switchButton.textContent = count
        ? `Review or switch ${count} saved ${activeProviderLabel()} response${count === 1 ? "" : "s"}`
        : `No saved ${activeProviderLabel()} responses`;
    } catch (_error) {
      if (revision !== profileRevision) return;
      switchButton.disabled = true;
      switchButton.textContent = `Saved ${activeProviderLabel()} responses unavailable`;
    }
  };

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

  const breakdownFor = (response, type) => (response.breakdowns || []).find((item) => item.type === type);

  const renderBreakdown = (response, type, label) => {
    const section = element("section", undefined, "guidance-breakdown");
    section.append(element("h4", label));
    const table = element("table", undefined, "guidance-rate-table");
    const head = element("thead");
    const headRow = element("tr");
    ["Upper bracket", "Rate", ""].forEach((title) => headRow.append(element("th", title)));
    head.append(headRow);
    table.append(head);
    const body = element("tbody");
    const breakdown = breakdownFor(response, type);
    for (const [index, bracket] of (breakdown ? breakdown.brackets || [] : []).entries()) {
      const row = element("tr");
      const threshold = document.createElement("input");
      threshold.type = "number";
      threshold.min = "0";
      threshold.step = "1";
      threshold.placeholder = "Top bracket";
      threshold.value = bracket.bracket ?? "";
      threshold.setAttribute("aria-label", `${label} bracket ${index + 1} upper limit`);
      threshold.addEventListener("input", () => { bracket.bracket = threshold.value === "" ? null : Number(threshold.value); });
      const rate = document.createElement("input");
      rate.type = "number";
      rate.min = "0";
      rate.max = "100";
      rate.step = "0.001";
      rate.value = bracket.rate ?? "";
      rate.setAttribute("aria-label", `${label} bracket ${index + 1} rate percentage`);
      rate.addEventListener("input", () => { bracket.rate = rate.value === "" ? "" : Number(rate.value); });
      const remove = element("button", "Remove", "remove-bracket");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove ${label} bracket ${index + 1}`);
      remove.addEventListener("click", () => {
        breakdown.brackets.splice(index, 1);
        render();
      });
      const thresholdCell = element("td");
      const rateCell = element("td");
      const actionCell = element("td");
      thresholdCell.append(threshold);
      rateCell.append(rate);
      actionCell.append(remove);
      row.append(thresholdCell, rateCell, actionCell);
      body.append(row);
    }
    table.append(body);
    section.append(table);
    const add = element("button", "Add bracket", "add-bracket");
    add.type = "button";
    add.addEventListener("click", () => {
      const brackets = breakdown.brackets;
      const topBracket = brackets.findIndex((item) => item.bracket === null);
      brackets.splice(topBracket === -1 ? brackets.length : topBracket, 0, { bracket: 0, rate: 0 });
      render();
    });
    section.append(add);
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
      const deductionLabel = element("label", `Standard deduction · ${String(deduction.filing_status || "").replaceAll("_", " ")}`, "deduction");
      const deductionAmount = document.createElement("input");
      deductionAmount.type = "number";
      deductionAmount.min = "0";
      deductionAmount.step = "1";
      deductionAmount.value = deduction.amount ?? "";
      deductionAmount.setAttribute("aria-label", `Response ${index + 1} standard deduction`);
      deductionAmount.addEventListener("input", () => { deduction.amount = deductionAmount.value === "" ? "" : Number(deductionAmount.value); });
      deductionLabel.append(deductionAmount);
      card.append(deductionLabel);
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
  profileInputs.forEach((input) => {
    input.addEventListener("input", syncProfileControls);
    input.addEventListener("change", syncProfileControls);
  });
  syncProfileControls();
  closeButton.addEventListener("click", () => { abortQueries(); dialog.close(); });
  dialog.addEventListener("cancel", () => abortQueries());
})();
</script>'''
