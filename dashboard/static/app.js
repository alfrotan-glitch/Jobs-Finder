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

function jobCard(job) {
  const route = job.package?.application_route || job.apply_url || job.url || "";
  const readiness = job.readiness || job.match?.readiness_status || "Needs review";
  const canPrepare = readiness !== "NOT_ELIGIBLE";
  return `
    <article class="card">
      <div class="cardTop">
        <div>
          <h3>${escapeHtml(job.title)}</h3>
          <p>${escapeHtml(job.company)} · ${escapeHtml(job.location || "Location not listed")}</p>
        </div>
        <span class="pill ${escapeHtml(readiness).toLowerCase()}">${escapeHtml(readiness)}</span>
      </div>
      <p><strong>Deadline:</strong> ${escapeHtml(deadline(job))}</p>
      <p><strong>Match:</strong> ${escapeHtml(matchLine(job))}</p>
      ${job.match?.explanation ? `<p class="muted">${escapeHtml(job.match.explanation)}</p>` : ""}
      <div class="actions">
        ${canPrepare ? `<button onclick="prepareJob('${escapeHtml(job.id)}')">Prepare package</button>` : ""}
        ${route ? `<a class="button secondary" href="${escapeHtml(route)}" target="_blank" rel="noopener">Open official route</a>` : ""}
      </div>
    </article>`;
}

function render() {
  $("recommendedList").innerHTML = state.recommended.length ? state.recommended.map(jobCard).join("") : `<div class="card">No recommendations yet. Press “Find Jobs”.</div>`;
  $("jobsList").innerHTML = state.jobs.length ? state.jobs.map(jobCard).join("") : `<div class="card">No jobs stored yet.</div>`;
  const applicationJobs = state.jobs.filter(j => ["PACKAGE_READY", "APPLIED_MANUALLY"].includes(j.status));
  $("applicationsList").innerHTML = applicationJobs.length ? applicationJobs.map(jobCard).join("") : `<div class="card">No prepared packages yet.</div>`;
}

async function refresh() {
  const [recommended, jobs, profile] = await Promise.all([
    fetch("/api/recommended").then(r => r.json()),
    fetch("/api/jobs").then(r => r.json()),
    fetch("/api/profile").then(r => r.json()),
  ]);
  state.recommended = recommended.jobs || [];
  state.jobs = jobs.jobs || [];
  const p = profile.summary || {};
  $("profileBox").innerHTML = profile.exists ? `
    <p><strong>Name:</strong> ${escapeHtml(p.name || "Not set")}</p>
    <p><strong>Email:</strong> ${escapeHtml(p.email || "Not set")}</p>
    <p><strong>Phone:</strong> ${escapeHtml(p.phone || "Not set")}</p>
    <p><strong>Location:</strong> ${escapeHtml(p.location || "Not set")}</p>
    <p><strong>Resume:</strong> ${escapeHtml(p.resume_path || "Not set")}</p>
    <p><strong>Preferred roles:</strong> ${escapeHtml((p.roles || []).join(", ") || "Not set")}</p>
  ` : `Copy <code>profile.yaml.example</code> to <code>profile.yaml</code> and enter verified facts.`;
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

for (const button of document.querySelectorAll(".tabs button")) {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    button.classList.add("active");
    $(button.dataset.tab).classList.add("active");
  });
}

$("findJobs").addEventListener("click", findJobs);
refresh().catch(error => setStatus(error.message, "error"));
