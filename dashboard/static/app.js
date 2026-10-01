const state = { jobs: [], recommended: [], lastScan: null };

const $ = (id) => document.getElementById(id);

function setStatus(message, kind = "") {
  const el = $("status");
  el.textContent = message;
  el.className = `status ${kind}`.trim();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
}

function deadline(job) {
  return job.metadata?.closing_date || job.match?.facts?.closing_date || "Not listed";
}

function matchLine(job) {
  const match = job.match || {};
  if (match.counts) {
    return `${match.counts["Met"] || 0} met · ${match.counts["Needs verification"] || 0} needs verification · ${match.counts["Not met"] || 0} not met`;
  }
  return job.readiness || "Needs review";
}

function readinessLabel(job) {
  const readiness = job.readiness || job.match?.readiness_status || "";
  if (readiness === "READY_TO_APPLY" && job.status !== "PACKAGE_READY" && job.status !== "APPLIED_MANUALLY") {
    return "ELIGIBLE — REVIEW PACKAGE";
  }
  if (readiness === "NEEDS_VERIFICATION") return "ELIGIBLE — VERIFY FIRST";
  return readiness || "NEEDS REVIEW";
}

function jobCard(job) {
  const route = job.package?.application_route || job.apply_url || job.url || "";
  const readiness = job.readiness || job.match?.readiness_status || "Needs review";
  const displayReadiness = readinessLabel(job);
  const canPrepare = readiness !== "NOT_ELIGIBLE";
  return `
    <article class="card">
      <div class="cardTop">
        <div>
          <h3>${escapeHtml(job.title)}</h3>
          <p>${escapeHtml(job.company)} · ${escapeHtml(job.location || "Location not listed")}</p>
        </div>
        <span class="pill ${escapeHtml(readiness).toLowerCase()}">${escapeHtml(displayReadiness)}</span>
      </div>
      <p><strong>Deadline:</strong> ${escapeHtml(deadline(job))}</p>
      <p><strong>Eligibility:</strong> ${escapeHtml(displayReadiness)}</p>
      ${job.package?.package_status ? `<p><strong>Package:</strong> ${escapeHtml(job.package.package_status)}</p>` : ""}
      <p><strong>Match:</strong> ${escapeHtml(matchLine(job))}</p>
      ${job.match?.explanation ? `<p class="muted">${escapeHtml(job.match.explanation)}</p>` : ""}
      <div class="actions">
        ${canPrepare ? `<button onclick="prepareJob('${escapeHtml(job.id)}')">Prepare package</button>` : ""}
        ${route ? `<a class="button secondary" href="${escapeHtml(route)}" target="_blank" rel="noopener">Open official route</a>` : ""}
        ${["PACKAGE_READY", "PACKAGE_NEEDS_INPUT"].includes(job.status) ? `<button class="secondary" onclick="markApplied('${escapeHtml(job.id)}')">Mark applied manually</button>` : ""}
      </div>
    </article>`;
}

function render() {
  $("recommendedList").innerHTML = state.recommended.length ? state.recommended.map(jobCard).join("") : `<div class="card">No recommendations yet. Press “Find Jobs”.</div>`;
  $("jobsList").innerHTML = state.jobs.length ? state.jobs.map(jobCard).join("") : `<div class="card">No jobs stored yet.</div>`;
  const applicationJobs = state.jobs.filter(j => ["PACKAGE_READY", "PACKAGE_NEEDS_INPUT", "APPLIED_MANUALLY"].includes(j.status));
  $("applicationsList").innerHTML = applicationJobs.length ? applicationJobs.map(jobCard).join("") : `<div class="card">No prepared packages yet.</div>`;
}

function statusPillClass(status) {
  if (status === "Verified") return "ready_to_apply";
  if (status === "Needs verification") return "needs_verification";
  return "not_eligible";
}

function renderProfileReview(review) {
  const box = $("profileReview");
  if (!review || !review.fields || !review.fields.length) {
    box.innerHTML = `<p class="muted">No profile loaded yet.</p>`;
    return;
  }
  const draftBanner = review.is_draft
    ? `<p class="status warn">DRAFT — needs review. ${escapeHtml(review.draft_note || "Confirm each fact below before scanning or applying.")}</p>`
    : "";
  const rows = review.fields.map(f => `
    <div class="cardTop" style="margin-bottom:.6rem;">
      <div>
        <strong>${escapeHtml(f.label)}</strong>
        ${(f.evidence || []).map(e => `<p class="muted">${escapeHtml(e)}</p>`).join("")}
      </div>
      <div style="display:flex; gap:.5rem; align-items:center;">
        <span class="pill ${statusPillClass(f.status)}">${escapeHtml(f.status)}</span>
        ${f.status !== "Verified" && f.confirm_field ? `<button class="secondary" onclick="confirmField('${escapeHtml(f.confirm_field)}')">Mark verified</button>` : ""}
      </div>
    </div>`).join("");
  box.innerHTML = draftBanner + rows;
}

async function confirmField(field) {
  const body = {field};
  if (field.startsWith("language:")) {
    const name = field.split(":")[1];
    const level = window.prompt(`Confirm your ${name} proficiency level (e.g. Native, Fluent, Professional, Basic):`, "");
    if (!level || !level.trim()) { setStatus("Confirmation cancelled: a proficiency level is required.", "warn"); return; }
    body.level = level.trim();
  }
  setStatus(`Confirming ${field}…`);
  try {
    const response = await fetch("/api/profile/confirm", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not confirm field");
    setStatus(data.message, "ok");
    renderProfileReview(data.review);
    await refresh();
  } catch (error) { setStatus(error.message, "error"); }
}
window.confirmField = confirmField;

async function importCv() {
  const input = $("cvFile");
  if (!input.files || !input.files[0]) { setStatus("Choose a CV file first.", "error"); return; }
  const form = new FormData();
  form.append("file", input.files[0]);
  setStatus("Importing CV…");
  try {
    const response = await fetch("/api/import-cv", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "CV import failed");
    setStatus(data.message, "warn");
    renderProfileReview(data);
    await refresh();
  } catch (error) { setStatus(error.message, "error"); }
}

async function loadSettings() {
  try {
    const settings = await fetch("/api/settings").then(r => r.json());
    const sources = (settings.sources || []).map(s => `<li><strong>${escapeHtml(s.name)}</strong> — Tier ${escapeHtml(s.tier)} ${s.active ? "(active)" : "(inactive)"}</li>`).join("");
    $("settingsBox").innerHTML = `
      <h3>Active sources</h3>
      <ul>${sources}</ul>
      <h3>Current ACBAR scan budget</h3>
      <p class="muted">${escapeHtml(settings.acbar?.note || "")}</p>
      <p>Max pages per scan: <strong>${escapeHtml(settings.acbar?.max_pages)}</strong> ·
         Detail fetch limit: <strong>${escapeHtml(settings.acbar?.detail_limit)}</strong> ·
         Concurrent detail fetches: <strong>${escapeHtml(settings.acbar?.max_detail_concurrency)}</strong> ·
         Timeout: <strong>${escapeHtml(settings.acbar?.timeout_seconds)}s</strong></p>
      <h3>ReliefWeb</h3>
      <p>Result limit: <strong>${escapeHtml(settings.reliefweb?.limit)}</strong> · Timeout: <strong>${escapeHtml(settings.reliefweb?.timeout_seconds)}s</strong></p>
      <h3>Safety</h3>
      <p>Automatic background scanning: <strong>${settings.background_scanning ? "Enabled" : "Disabled"}</strong>. Use “Find Jobs” to scan on demand.</p>
      <p>Automatic application submission: <strong>${settings.automatic_submission ? "Enabled" : "Disabled"}</strong>. Applications are always opened for manual review and submission.</p>
      <p class="muted">These are the current, non-editable system settings. There is no hidden configuration beyond what is shown here.</p>
    `;
  } catch (error) {
    $("settingsBox").innerHTML = `<p class="muted">Could not load settings: ${escapeHtml(error.message)}</p>`;
  }
}

async function refresh() {
  const [recommended, jobs, profile, review] = await Promise.all([
    fetch("/api/recommended").then(r => r.json()),
    fetch("/api/jobs").then(r => r.json()),
    fetch("/api/profile").then(r => r.json()),
    fetch("/api/profile/review").then(r => r.json()),
  ]);
  state.recommended = recommended.jobs || [];
  state.jobs = jobs.jobs || [];
  const p = profile.summary || {};
  $("profileBox").innerHTML = profile.exists ? `
    ${p.is_draft ? `<p class="status warn">DRAFT — review before use. ${escapeHtml(p.draft_note || "")}</p>` : ""}
    <p><strong>Name:</strong> ${escapeHtml(p.name || "Not set")}</p>
    <p><strong>Email:</strong> ${escapeHtml(p.email || "Not set")}</p>
    <p><strong>Phone:</strong> ${escapeHtml(p.phone || "Not set")}</p>
    <p><strong>Location:</strong> ${escapeHtml(p.location || "Not set")}</p>
    <p><strong>Resume:</strong> ${escapeHtml(p.resume_path || "Not set")}</p>
    <p><strong>Preferred roles:</strong> ${escapeHtml((p.roles || []).join(", ") || "Not set")}</p>
  ` : `Copy <code>profile.yaml.example</code> to <code>profile.yaml</code> and enter verified facts, or import a CV below.`;
  renderProfileReview(review);
  render();
}

async function findJobs() {
  setStatus("Scanning reachable Afghanistan sources…");
  try {
    const response = await fetch("/api/find", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Scan failed");
    state.lastScan = data;
    $("advancedLog").textContent = JSON.stringify(data, null, 2);
    const kind = data.status === "SCAN_COMPLETE" ? "ok" : data.status === "PARTIAL_SCAN" ? "warn" : "error";
    setStatus(data.message || data.status, kind);
    await refresh();
  } catch (error) {
    setStatus(error.message, "error");
  }
}

async function prepareJob(id) {
  setStatus("Preparing application package…");
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(id)}/prepare`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not prepare package");
    $("advancedLog").textContent = JSON.stringify(data, null, 2);
    setStatus("Package prepared. Review the generated CV, cover letter, and instructions before applying.", "ok");
    await refresh();
  } catch (error) {
    setStatus(error.message, "error");
  }
}
window.prepareJob = prepareJob;

async function markApplied(id) {
  const confirmation = window.prompt(`If you manually submitted this application, type APPLIED ${id}`) || "";
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(id)}/mark-applied`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({confirmation})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Application was not recorded");
    setStatus(data.message, "ok"); await refresh();
  } catch (error) { setStatus(error.message, "error"); }
}
window.markApplied = markApplied;

for (const button of document.querySelectorAll(".tabs button")) {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    button.classList.add("active");
    $(button.dataset.tab).classList.add("active");
  });
}

$("findJobs").addEventListener("click", findJobs);
$("importCvBtn").addEventListener("click", importCv);
refresh().catch(error => setStatus(error.message, "error"));
loadSettings().catch(error => setStatus(error.message, "error"));
