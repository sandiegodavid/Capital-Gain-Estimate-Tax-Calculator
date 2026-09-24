document.addEventListener("DOMContentLoaded", () => {
  const $ = (id) => document.getElementById(id);
  const bindDialog = (openId, dialogId, closeId) => {
    const open = $(openId), dialog = $(dialogId), close = $(closeId);
    if (open && dialog && close) {
      open.addEventListener("click", () => dialog.showModal());
      close.addEventListener("click", () => dialog.close());
    }
  };
  bindDialog("show-tax-formula", "tax-formula-dialog", "close-tax-formula");
  bindDialog("show-tax-rules", "tax-rules-dialog", "close-tax-rules");

  const status = $("source-folder-status"), sourceValue = $("source-folder-value"), sourcePath = $("source-folder-path");
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin || event.data?.type !== "finder-result" || !status) return;
    status.textContent = event.data.message;
    status.classList.toggle("error", !event.data.ok);
    if (event.data.source) {
      if (sourceValue) sourceValue.value = event.data.source;
      if (sourcePath) {
        sourcePath.textContent = event.data.source;
        sourcePath.title = event.data.source;
      }
    }
    if (event.data.setup_parent) {
      const form = $("setup-realized-gains-form"), parent = $("setup-realized-gains-parent"), year = $("setup-realized-gains-year"), saleYear = $("sale-year");
      if (!form || !parent || !year) return;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Set up folders";
      button.addEventListener("click", () => {
        parent.value = event.data.setup_parent;
        year.value = saleYear?.value || String(new Date().getFullYear());
        form.requestSubmit();
      });
      status.replaceChildren(document.createTextNode("Create a standard Realized Gains folder here? "), button);
    }
  });

  const taxForm = document.querySelector(".tax-form"), stale = $("tax-estimate-stale"), key = "capital-gain-estimate-scroll-y", saved = sessionStorage.getItem(key);
  let output = $("tax-estimate-output"), updateTimer, activeEstimateRequest;
  const clearEstimate = () => {
    if (output && stale) {
      output.hidden = true;
      stale.hidden = false;
    }
  };
  const updateEstimate = async () => {
    if (!taxForm?.checkValidity()) return;
    activeEstimateRequest?.abort();
    activeEstimateRequest = new AbortController();
    const url = new URL(taxForm.action, window.location.origin);
    url.search = new URLSearchParams(new FormData(taxForm)).toString();
    try {
      const response = await fetch(url, { signal: activeEstimateRequest.signal });
      if (!response.ok) throw new Error(`Estimate request failed: ${response.status}`);
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const updatedOutput = page.getElementById("tax-estimate-output");
      if (!updatedOutput || !output) throw new Error("Updated estimate is unavailable.");
      output.replaceWith(updatedOutput);
      output = updatedOutput;
      stale.hidden = true;
      bindDialog("show-tax-formula", "tax-formula-dialog", "close-tax-formula");
      bindDialog("show-tax-rules", "tax-rules-dialog", "close-tax-rules");
    } catch (error) {
      if (error.name !== "AbortError") clearEstimate();
    }
  };
  const queueEstimateUpdate = () => {
    clearTimeout(updateTimer);
    updateTimer = setTimeout(updateEstimate, 350);
  };
  if (saved !== null) {
    sessionStorage.removeItem(key);
    requestAnimationFrame(() => scrollTo(0, Number(saved)));
  }
  taxForm?.querySelectorAll("#state-residence,#filing-status").forEach((control) => {
    control.addEventListener("input", clearEstimate);
    control.addEventListener("change", clearEstimate);
  });
  taxForm?.querySelectorAll("#qualified-children,#other-dependents,#ordinary-income,#short-term-carryover-loss,#long-term-carryover-loss").forEach((control) => {
    control.addEventListener("input", queueEstimateUpdate);
    control.addEventListener("change", updateEstimate);
  });
  taxForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    updateEstimate();
  });

  const toggles = [...document.querySelectorAll("[data-source-toggle]")];
  toggles.forEach((toggle) => toggle.addEventListener("change", () => {
    const selected = toggles.filter((item) => item.checked);
    if (!selected.length) {
      toggle.checked = true;
      return;
    }
    const url = new URL(location.href);
    url.searchParams.set("source_selection", "1");
    url.searchParams.delete("included_source");
    selected.forEach((item) => url.searchParams.append("included_source", item.value));
    url.hash = "included-sources";
    location.assign(url);
  }));
});
