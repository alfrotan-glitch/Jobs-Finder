const state = {
  jobs: [],
  applications: [],
  jobsMeta: {total: 0, has_more: false, counts: {}},
  applicationsMeta: {total: 0, has_more: false},
  recommended: [],
  recommendationContext: null,
  recommendationOrigin: "",
  profile: {},
  profileDetails: {},
  profileReview: {},
  settings: {},
  lastScan: null,
  alerts: {alerts: [], unread_count: 0},
  monitorSchedule: {supported: false, enabled: false, time: "09:00"},
  currentTab: "dashboard",
  selectedJob: null,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

// Employer-provided links are untrusted even after HTML-attribute escaping.
function safeExternalUrl(value) {
  const raw = String(value ?? "").trim();
  if (!raw || /[\x00-\x20\x7f]/.test(raw)) return "";
  try {
    const url = new URL(raw);
    return ["https:", "http:"].includes(url.protocol) && url.hostname &&
      !url.username && !url.password ? url.href : "";
  } catch (_) {
    return "";
  }
}

function compactText(value, fallback = "Not listed") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function initials(name) {
  const parts = String(name || "Jobs Finder").trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] || "J") + (parts[1]?.[0] || "F");
}

function setStatus(message, kind = "") {
  const el = $("status");
  el.textContent = message;
  el.className = `notice ${kind}`.trim();
  $("sidebarSystemStatus").textContent = kind === "error" ? "Needs attention" : kind === "warn" ? "Review" : "Ready";
  $("topScanStatus").className = `scanStatus ${kind}`.trim();
  $("topScanStatus").innerHTML = `<span></span> ${escapeHtml(kind === "error" ? "Attention" : kind === "warn" ? "Review" : "Ready")}`;
}

function humanizeError(message) {
  const text = String(message || "");
  if (/TLS|SSL|EOF|connection/i.test(text)) {
    return "Job source temporarily unavailable. Technical details are available in Advanced.";
  }
  if (/profile\.yaml/i.test(text)) return text.replace(/profile\.yaml/gi, "your local profile");
  if (/Profile/i.test(text)) return text;
  return text || "Something went wrong. Please try again.";
}

function deadline(job) {
  return job.metadata?.closing_date || job.match?.facts?.closing_date || "Not listed";
}

function sourceName(job) {
  return job.metadata?.source_name || job.match?.facts?.source_name || job.source || "Not listed";
}

function applicationMethod(job) {
  // Officially refreshed application forms outrank older saved package drafts.
  // This prevents an obsolete email draft from hiding a verified WEB route.
  if (job.metadata?.application_method === "WEB" && job.metadata?.apply_url) return "WEB";
  return (job.metadata?.application_method || job.application_method || job.match?.facts?.application_method || job.package?.application_method || "UNAVAILABLE").toUpperCase();
}

function applyEmail(job) {
  return job.metadata?.apply_email || job.match?.facts?.apply_email || job.match?.facts?.application_email || job.apply_email || job.package?.apply_email || "";
}

function webApplyUrl(job) {
  return job.metadata?.apply_url || job.apply_url || job.match?.facts?.apply_url || job.match?.facts?.application_url || job.package?.apply_url || "";
}

function vacancyPage(job) {
  return job.metadata?.vacancy_url || job.match?.facts?.vacancy_url || job.url || job.package?.official_vacancy_page || "";
}

function readinessValue(job) {
  return job.readiness || job.match?.readiness_status || "";
}

function readinessLabel(job) {
  if (job.is_expired) return "DEADLINE PASSED";
  if (job.status === "APPLIED_MANUALLY") return "APPLIED MANUALLY";
  const readiness = readinessValue(job);
  if (readiness === "READY_TO_APPLY") return "READY TO APPLY";
  if (readiness === "NEEDS_VERIFICATION") return "REQUIRES VERIFICATION";
  if (readiness === "NOT_ELIGIBLE") return "NOT ELIGIBLE";
  return readiness || "NEEDS REVIEW";
}

function friendlyStatus(value) {
  const text = String(value || "").replace(/_/g, " ").trim().toLowerCase();
  return text ? text.replace(/\b\w/g, (c) => c.toUpperCase()) : "Needs Review";
}

function statusClass(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_");
}

function methodLabel(method) {
  if (method === "EMAIL") return "Email";
  if (method === "WEB") return "Web";
  return "Unavailable";
}

function methodDescription(job) {
  const method = applicationMethod(job);
  if (method === "EMAIL" && applyEmail(job)) return `Apply by email · ${applyEmail(job)}`;
  if (method === "WEB" && webApplyUrl(job)) return "Apply online";
  return "Application route unavailable";
}

function scanStatusLabel(status) {
  if (status === "SCANNED") return "Scanned";
  if (status === "PARTIAL") return "Partial";
  if (status === "UNAVAILABLE") return "Unavailable";
  if (status === "FAILED") return "Failed";
  return friendlyStatus(status || "Not run");
}

function sourceSummaryLine(source) {
  const n = (key) => Number(source[key] || 0);
  const parts = [
    `${n("listings_seen")} listings seen`,
    `${n("listing_parse_failures")} parse failures`,
    `${n("vacancies_parsed")} valid vacancies processed`,
    `${n("not_processed_due_to_budget")} deferred by budget`,
    `${n("duplicates_removed")} duplicates`,
    `${n("expired_excluded")} expired`,
    `${n("irrelevant_excluded")} irrelevant`,
    `${n("incompatible_role_classification_excluded")} incompatible role classifications`,
    `${n("source_validation_excluded")} source-invalid`,
    `${n("relevant_retained")} retained`,
    `${n("application_routes_found")} routes found / ${n("application_routes_unavailable")} unavailable`,
  ];
  if ((source.partial_reasons || []).length) parts.push(`Partial because: ${source.partial_reasons.join(", ")}`);
  if (!source.ok && source.status) parts.push("Unavailable is not counted as zero market results");
  return parts.join(" · ");
}

function requirementsByStatus(job, status) {
  return (job.match?.requirement_matches || []).filter((item) => item.status === status);
}

function requirementLabels(job, status = "Met", limit = 4) {
  const skip = /source|application|destination|closing date|role family|official vacancy/i;
  return requirementsByStatus(job, status)
    .map((item) => item.label || item.key || "Requirement")
    .filter((label) => label && !skip.test(label))
    .slice(0, limit);
}

function fitSummary(job) {
  const labels = requirementLabels(job, "Met", 4);
  if (labels.length) return `Your profile aligns with ${labels.join(" · ")}.`;
  const readiness = readinessValue(job);
  if (readiness === "NEEDS_VERIFICATION") return "Some requirements need confirmation before this can be treated as ready.";
  if (readiness === "NOT_ELIGIBLE") return "The assessment identified a requirement that does not match the verified profile.";
  return "Open details to review the requirement assessment.";
}

function directApplicationRouteAvailable(job) {
  const method = applicationMethod(job);
  return (method === "EMAIL" && Boolean(applyEmail(job))) || (method === "WEB" && Boolean(safeExternalUrl(webApplyUrl(job))));
}

// The browser must never label an incomplete, submitted, expired, or
// superseded email package as ready to open. The server enforces this again.
function emailDraftReady(job) {
  const pkg = job.package || {};
  return !job.is_expired && job.status !== "APPLIED_MANUALLY" &&
    applicationMethod(job) === "EMAIL" && pkg.route_type === "email" &&
    pkg.package_status === "READY_FOR_REVIEW" &&
    !(pkg.missing_items || []).length && Boolean(pkg.email_draft) &&
    Boolean(applyEmail(job));
}

function canPrepareJob(job) {
  return readinessValue(job) !== "NOT_ELIGIBLE" &&
    !job.is_expired && job.status !== "APPLIED_MANUALLY";
}

function packageExists(job) {
  return ["PACKAGE_READY", "PACKAGE_NEEDS_INPUT", "APPLIED_MANUALLY"].includes(job.status) || Boolean(job.package?.package_status);
}

function packageReadyForReview(job) {
  return job.status === "APPLIED_MANUALLY" || job.status === "PACKAGE_READY" || job.package?.package_status === "READY_FOR_REVIEW";
}

function generatedPaths(job) {
  return job.documents?.generated_paths || job.generated_paths || {};
}

function openFileUrl(path, download = false) {
  const query = `path=${encodeURIComponent(path)}`;
  return `/api/generated-file?${query}${download ? "&download=1" : ""}`;
}

function jobCard(job, {compact = false} = {}) {
  const readiness = readinessValue(job);
  const method = applicationMethod(job);
  const labels = requirementLabels(job, "Met", compact ? 3 : 5);
  const id = escapeAttr(job.id);
  const org = compactText(job.company, "Organization not listed");
  const location = compactText(job.location, "Location not listed");
  const canPrepare = canPrepareJob(job);
  return `
    <article class="jobCard ${compact ? "compact" : ""}">
      <div class="jobCardHeader">
        <div class="jobTitleBlock">
          <h3>${escapeHtml(job.title || "Untitled vacancy")}</h3>
          <p>${escapeHtml(org)} · ${escapeHtml(location)}</p>
        </div>
        <span class="statusBadge ${job.is_expired ? "expired" : statusClass(job.status === "APPLIED_MANUALLY" ? "APPLIED_MANUALLY" : readiness)}">${escapeHtml(readinessLabel(job))}</span>
      </div>
      <div class="jobMetaRow" aria-label="Vacancy metadata">
        <span>Deadline: ${escapeHtml(deadline(job))}</span>
        <span>${escapeHtml(methodLabel(method))}</span>
        <span>${escapeHtml(sourceName(job))}</span>
      </div>
      <div class="fitBox">
        <strong>Why this fits</strong>
        <p>${escapeHtml(fitSummary(job))}</p>
        ${labels.length ? `<div class="tagRow">${labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("")}</div>` : ""}
      </div>
      <div class="cardActions">
        <button class="secondary" data-action="view-job" data-job-id="${id}">View details</button>
        ${canPrepare && directApplicationRouteAvailable(job) ? `<button class="primary subtle" data-action="${method === "EMAIL" && emailDraftReady(job) ? "apply-email" : "prepare-job"}" data-job-id="${id}">${method === "EMAIL" && emailDraftReady(job) ? "Apply · Attached email" : method === "EMAIL" ? "Prepare email + PDFs" : "Prepare application"}</button>` : ""}
        ${packageExists(job) ? `<button class="secondary" data-action="review-package" data-job-id="${id}">Review package</button>` : ""}
        ${packageReadyForReview(job) && canPrepareJob(job) ? `<button class="secondary" data-action="mark-applied" data-job-id="${id}">Mark applied</button>` : ""}
      </div>
    </article>`;
}

function emptyState(title, body, action = "") {
  return `<div class="emptyState"><div class="emptyIcon" aria-hidden="true">□</div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(body)}</p>${action}</div>`;
}

function skeletonCards(count = 3) {
  return Array.from({length: count}, () => `<div class="skeletonCard"><span></span><span></span><span></span></div>`).join("");
}

function setLoadingLists() {
  for (const id of ["dashboardRecommendedList", "recommendedList", "jobsList", "applicationsList"]) {
    const el = $(id);
    if (el) el.innerHTML = skeletonCards(id === "dashboardRecommendedList" ? 2 : 3);
  }
}

function renderMetrics() {
  const counts = state.jobsMeta.counts || {};
  $("metricRecommended").textContent = state.recommended.length;
  $("metricJobs").textContent = state.jobsMeta.total ?? state.jobs.length;
  $("metricReady").textContent = counts.ready_to_apply ?? 0;
  $("metricApplications").textContent = (counts.package || 0) + (counts.applied || 0);
}

function renderAlerts() {
  const inbox = state.alerts || {alerts: [], unread_count: 0};
  const notices = inbox.alerts || [];
  const unread = Number(inbox.unread_count || 0);
  const counter = $("alertNavCount");
  counter.hidden = unread === 0;
  counter.textContent = unread > 99 ? "99+" : String(unread);
  $("alertInboxSummary").textContent = unread
    ? `${unread} unread notification${unread === 1 ? "" : "s"} · ${notices.length} recent`
    : "All caught up. New matches and deadline reminders will appear here.";
  const itemHtml = (item) => {
    const route = item.job_id
      ? `<button class="secondary smallButton" data-action="view-job" data-job-id="${escapeAttr(item.job_id)}">View vacancy</button>`
      : "";
    const label = item.kind === "NEW_MATCH" ? "New match" : item.kind === "DEADLINE" ? "Deadline reminder" : "Source issue";
    return `<article class="alertItem ${item.read_at ? "" : "unread"}">
      <div class="alertItemIcon" aria-hidden="true">${item.kind === "NEW_MATCH" ? "★" : item.kind === "DEADLINE" ? "⌛" : "!"}</div>
      <div class="alertItemBody">
        <span class="microLabel">${escapeHtml(label)} · ${escapeHtml(item.created_at || "")}</span>
        <h4>${escapeHtml(item.title || "Notification")}</h4>
        <p>${escapeHtml(item.message || "")}</p>
        <div class="cardActions">
          ${route}
          ${!item.read_at ? `<button class="textButton" data-action="mark-alert-read" data-alert-id="${escapeAttr(item.id)}">Mark read</button>` : ""}
        </div>
      </div>
    </article>`;
  };
  $("alertsList").innerHTML = notices.length
    ? notices.map(itemHtml).join("")
    : emptyState("No alerts yet", "Run Find Jobs once to record new matches. Enable daily checks in Settings for automatic updates while signed in.");
  $("dashboardAlerts").innerHTML = notices.length
    ? notices.slice(0, 3).map((item) => `<div class="alertDigest">
        <strong>${escapeHtml(item.title || "Alert")}</strong>
        <span>${escapeHtml(item.message || "")}</span>
      </div>`).join("")
    : `<p class="sectionHelp">No notifications yet. Your next scan will look for matching vacancies and upcoming deadlines.</p>`;
}

function renderMonitoringSchedule() {
  const monitor = state.monitorSchedule || {};
  const summary = $("monitoringSchedule");
  if (!monitor.supported) {
    summary.innerHTML = `<p>Scheduled daily checks require Windows.</p><p class="sectionHelp">You can still use Find Jobs and review saved alerts manually.</p>`;
    return;
  }
  if (monitor.error) {
    summary.innerHTML = `<p class="sectionHelp">${escapeHtml(monitor.error)}</p><button class="secondary smallButton" data-action="refresh-monitor-status">Retry status check</button>`;
    return;
  }
  summary.innerHTML = `<p><strong>${monitor.enabled ? "Daily checks enabled" : "Daily checks off"}</strong></p>
    <p class="sectionHelp">At ${escapeHtml(monitor.time || "09:00")} (Windows local time), Windows will look for suitable vacancies and approaching deadlines.</p>
    <p class="sectionHelp">Your computer must be on and you must be signed in. The dashboard can be closed. Alerts are stored here; no job applications are submitted.</p>
    <button class="${monitor.enabled ? "secondary" : "primary subtle"}" data-action="toggle-daily-check" data-enabled="${monitor.enabled ? "false" : "true"}">${monitor.enabled ? "Disable daily checks" : "Enable daily checks"}</button>`;
}

async function changeDailyChecks(enabled) {
  try {
    const result = await apiJson("/api/monitor/schedule", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({enabled}),
    });
    state.monitorSchedule = result;
    renderMonitoringSchedule();
    setStatus(enabled ? "Daily monitoring enabled for 9 AM while signed in." : "Daily monitoring disabled.", "ok");
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function markAlertRead(id) {
  try {
    await apiJson(`/api/alerts/${encodeURIComponent(id)}/read`, {method: "POST"});
    state.alerts = await apiJson("/api/alerts");
    renderAlerts();
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function markAllAlertsRead() {
  try {
    await apiJson("/api/alerts/read-all", {method: "POST"});
    state.alerts = await apiJson("/api/alerts");
    renderAlerts();
    setStatus("Notifications marked read.", "ok");
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

function renderScanSummary() {
  const box = $("scanSummaryBox");
  if (!box) return;
  const scan = state.lastScan;
  if (!scan) {
    box.innerHTML = `<p class="sectionHelp">No scan has run yet. Run Find Jobs to see source-by-source activity.</p>`;
    return;
  }
  const reports = scan.source_reports || [];
  const timeRange = [scan.started_at, scan.finished_at].filter(Boolean).join(" → ");
  const rows = reports.map((source) => `
    <div class="scanSourceItem">
      <div>
        <strong>${escapeHtml(source.name || source.id || "Source")}</strong>
        <span>${escapeHtml(source.source_url || "Official source URL not listed")}</span>
      </div>
      <span class="statusBadge ${statusClass(source.status || (source.ok ? "SCANNED" : "UNAVAILABLE"))}">${escapeHtml(scanStatusLabel(source.status || (source.ok ? "SCANNED" : "UNAVAILABLE")))}</span>
      <p>${escapeHtml(sourceSummaryLine(source))}</p>
    </div>`).join("");
  box.innerHTML = `
    <div class="scanOverview">
      <span class="statusBadge ${statusClass(scan.status)}">${escapeHtml(friendlyStatus(scan.status))}</span>
      <p>${escapeHtml(scan.message || "Scan completed.")}</p>
      ${timeRange ? `<p class="sectionHelp">${escapeHtml(timeRange)}</p>` : ""}
    </div>
    <div class="scanSourceList">${rows || `<p class="sectionHelp">No source reports were returned by the backend.</p>`}</div>`;
}

function renderNextStep() {
  const box = $("nextStepBox");
  const scanStatus = state.lastScan?.status;
  const available = state.recommended.filter((job) => !job.is_expired && job.status !== "APPLIED_MANUALLY");
  // A PARTIAL_SCAN may still contain dozens of useful vacancies. It must
  // never hide a deadline or tell the user that *all* sources failed.
  const ready = available.find((job) => readinessValue(job) === "READY_TO_APPLY");
  if (ready) {
    const hasPackage = packageExists(ready);
    box.innerHTML = `
      <div class="nextStepIcon ok" aria-hidden="true">✓</div>
      <h4>${hasPackage ? "Review your prepared application" : "Prepare the strongest application"}</h4>
      <p>${escapeHtml(ready.title)} · Deadline: ${escapeHtml(deadline(ready))}. Check the official posting before submitting.</p>
      <button class="primary subtle" data-action="${hasPackage ? "review-package" : "prepare-job"}" data-job-id="${escapeAttr(ready.id)}">${hasPackage ? "Review package" : "Prepare application"}</button>`;
    return;
  }
  const dated = available
    .filter((job) => /^\d{4}-\d{2}-\d{2}$/.test(deadline(job)))
    .sort((a, b) => deadline(a).localeCompare(deadline(b)));
  if (dated.length) {
    const soonest = dated[0];
    box.innerHTML = `
      <div class="nextStepIcon warn" aria-hidden="true">!</div>
      <h4>Check requirements before the deadline</h4>
      <p>${escapeHtml(soonest.title)} closes on ${escapeHtml(deadline(soonest))}. Your match still requires verification; review the official application route.</p>
      <button class="primary subtle" data-action="view-job" data-job-id="${escapeAttr(soonest.id)}">Review vacancy</button>
      ${scanStatus === "PARTIAL_SCAN" ? '<p class="sectionHelp">Some source details were incomplete. Other discovered jobs remain available.</p>' : ""}`;
    return;
  }
  if (available.length) {
    box.innerHTML = `
      <div class="nextStepIcon" aria-hidden="true">◦</div>
      <h4>Review open requirements</h4>
      <p>Recommended jobs need verification before applying. Confirm requirements and check the official deadlines.</p>
      <button class="secondary" data-tab-target="recommended">Review recommendations</button>`;
    return;
  }
  if (scanStatus === "SOURCES_UNAVAILABLE") {
    box.innerHTML = `
      <div class="nextStepIcon warn" aria-hidden="true">!</div>
      <h4>Job sources unavailable</h4>
      <p>None of the configured sources could be checked. Saved applications are preserved; retry the scan.</p>
      <button class="secondary" data-tab-target="advanced">View source details</button>`;
    return;
  }
  if (scanStatus === "PARTIAL_SCAN") {
    box.innerHTML = `
      <div class="nextStepIcon warn" aria-hidden="true">!</div>
      <h4>Some sources were partially checked</h4>
      <p>Results may be incomplete because one or more sources could not provide all vacancy details.</p>
      <button class="secondary" data-tab-target="advanced">Review scan details</button>`;
    return;
  }
  box.innerHTML = `
    <div class="nextStepIcon" aria-hidden="true">↻</div>
    <h4>${state.jobs.length ? "Review available jobs" : "Run a vacancy scan"}</h4>
    <p>${state.jobs.length ? "No current recommended vacancy is available. Review all discovered opportunities." : "Start with a scan to find suitable opportunities from the configured sources."}</p>
    ${state.jobs.length
      ? '<button class="primary subtle" data-tab-target="jobs">All jobs</button>'
      : '<button class="primary subtle" data-action="find-jobs">Find Jobs</button>'}`;
}

function recommendationProvenanceNotice() {
  const scan = state.recommendationContext;
  if (scan && (scan.finished_at || scan.started_at)) {
    const timestamp = scan.finished_at || scan.started_at;
    return `<p class="sectionHelp">Recommendations from the last saved scan (${escapeHtml(timestamp)}). Run a new scan to refresh source results.</p>`;
  }
  if (state.recommendationOrigin === "stored_history" && state.recommended.length) {
    return `<p class="sectionHelp">Showing saved recommendation history, not a live source result. Run a new scan to refresh it.</p>`;
  }
  return "";
}

function renderJobLists() {
  const sourceFailed = state.lastScan && ["SOURCES_UNAVAILABLE", "SCAN_FAILED"].includes(state.lastScan.status);
  const provenance = recommendationProvenanceNotice();
  const currentJobs = state.jobs.filter((job) => !job.is_expired);
  const historicalJobs = state.jobs.filter((job) => job.is_expired);
  const sourceAction = `<button class="secondary" data-tab-target="advanced">View details</button>`;
  $("dashboardRecommendedList").innerHTML = state.recommended.length
    ? provenance + state.recommended.slice(0, 4).map((job) => jobCard(job, {compact: true})).join("")
    : sourceFailed
      ? emptyState("Job sources could not be reached", "The last scan did not return live vacancies because source connections failed.", sourceAction)
      : emptyState("No recommendations yet", "Run a scan to find vacancies worth reviewing first.", `<button class="primary subtle" data-action="find-jobs">Find Jobs</button>`);
  $("recommendedList").innerHTML = state.recommended.length
    ? provenance + state.recommended.map((job) => jobCard(job)).join("")
    : sourceFailed
      ? emptyState("Job sources could not be reached", "No recommendation can be shown until a source returns vacancy data.", sourceAction)
      : emptyState("No suitable vacancies found yet", "Your last scan did not return actionable recommended vacancies.", `<button class="primary subtle" data-action="find-jobs">Run scan</button>`);
  $("jobsPaging").innerHTML = state.jobsMeta.has_more
    ? `<p class="sectionHelp">Showing ${state.jobs.length} of ${state.jobsMeta.total} stored vacancies.</p>
       <button class="secondary" data-action="load-more-jobs">Load more jobs</button>`
    : `<p class="sectionHelp">${state.jobsMeta.total || 0} total stored vacancies, including expired and previously reviewed entries.</p>`;
  $("jobsList").innerHTML = state.jobs.length
    ? currentJobs.map((job) => jobCard(job)).join("")
      + (historicalJobs.length
        ? `<p class="sectionHelp"><strong>Past-deadline vacancies</strong> — kept for your records, not open for preparation.</p>${historicalJobs.map((job) => jobCard(job)).join("")}`
        : "")
    : sourceFailed
      ? emptyState("Job sources could not be reached", "This is a source connectivity problem, not a finding that no jobs exist.", sourceAction)
      : emptyState("No jobs yet", "Run a scan to populate this list with actionable vacancies.", `<button class="primary subtle" data-action="find-jobs">Run scan</button>`);
}

function renderApplications() {
  // The pipeline counts the complete canonical ledger, not the current
  // 100-record page. Submitted or prepared records older than that page
  // remain visible in their own independently paginated Applications view.
  const counts = state.jobsMeta.counts || {};
  $("stageFound").textContent = counts.found || 0;
  $("stageReviewed").textContent = counts.reviewed || 0;
  $("stagePackage").textContent = counts.package || 0;
  $("stageApplied").textContent = counts.applied || 0;
  $("applicationsList").innerHTML = state.applications.length
    ? state.applications.map((job) => jobCard(job)).join("")
    : emptyState("No application packages yet", "Prepare a package from a recommended vacancy to start tracking it here.");
  $("applicationsPaging").innerHTML = state.applicationsMeta.has_more
    ? `<p class="sectionHelp">Showing ${state.applications.length} of ${state.applicationsMeta.total} saved applications.</p>
       <button class="secondary" data-action="load-more-applications">Load more applications</button>`
    : `<p class="sectionHelp">${state.applicationsMeta.total || 0} saved application records.</p>`;
}

function renderProfileIdentity() {
  const summary = state.profile?.summary || {};
  const name = summary.name || "Profile not loaded";
  const title = summary.title || "Professional profile";
  const location = summary.location || "Location not listed";
  const avatarText = initials(name);
  $("sidebarName").textContent = name;
  $("sidebarTitle").textContent = title.split("|")[0].trim() || title;
  $("topName").textContent = name === "Profile not loaded" ? "Jobs-Finder" : name;
  $("topRole").textContent = title;
  $("topAvatar").textContent = avatarText;
  $("sidebarAvatar").textContent = avatarText;
  $("welcomeName").textContent = name && name !== "Profile not loaded" ? `, ${name.split(" ")[0]}` : "";
  $("welcomeMeta").textContent = `${title} · ${location}`;
}

function renderProfileDetails() {
  const exists = state.profile?.exists;
  const details = state.profileDetails?.details || {};
  const summary = details.summary || state.profile?.summary || {};
  if (!exists) {
    $("profileHeader").innerHTML = emptyState("No profile loaded", "Create your canonical local profile. A CV preview never creates or replaces it.");
    for (const id of ["profileSummaryBox", "profileExperienceBox", "profileEducationBox", "profileRegistrationBox", "profileExitExamBox", "profileTrainingBox", "profileSkillsBox", "profileLanguagesBox"]) {
      $(id).innerHTML = `<p class="sectionHelp">No profile data available.</p>`;
    }
    return;
  }
  $("profileHeader").innerHTML = `
    <div class="profileHeroAvatar" aria-hidden="true">${escapeHtml(initials(summary.name))}</div>
    <div>
      <p class="microLabel">My Profile</p>
      <h2>${escapeHtml(summary.name || "Professional profile")}</h2>
      <p>${escapeHtml(summary.title || "Professional profile")} · ${escapeHtml(summary.location || "Location not listed")}</p>
      <div class="profileContact"><span>${escapeHtml(summary.email || "Email not set")}</span><span>${escapeHtml(summary.phone || "Phone not set")}</span></div>
    </div>`;
  $("profileSummaryBox").innerHTML = `<p>${escapeHtml(details.professional_summary || "No professional summary available.")}</p>`;
  $("profileExperienceBox").innerHTML = (details.experience || []).length
    ? details.experience.map((item) => `
      <article class="timelineItem">
        <div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.dates || "")}</span></div>
        <p>${escapeHtml(item.organization)}${item.location ? ` · ${escapeHtml(item.location)}` : ""}</p>
        ${(item.bullets || []).length ? `<ul>${item.bullets.slice(0, 6).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>` : ""}
        <div class="experienceImprove">
          <p class="sectionHelp"><strong>Make this CV stronger:</strong> Add an actual responsibility, scope, method or result from this position. Only write work you personally performed; never invent numbers.</p>
          <textarea rows="3" id="responsibility-${item.source_index}" placeholder="Example structure: Action you performed + who/what you worked with + methods/protocols + real result (only if known)."></textarea>
          <button class="secondary" data-action="add-responsibility" data-role-index="${item.source_index}">Add verified work detail</button>
        </div>
        ${(item.pending_bullets || []).length ? `<p class="sectionHelp">Awaiting your confirmation — these ${item.pending_bullets.length} detailed draft(s) are NOT used in any generated CV or cover letter until you verify them:</p><ul class="pendingList">${item.pending_bullets.map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>` : ""}
      </article>`).join("")
    : `<p class="sectionHelp">No professional experience listed.</p>`;
  $("profileEducationBox").innerHTML = renderSimpleList((details.education || []).map((item) => [item.degree, item.institution, item.dates].filter(Boolean).join(" — ")));
  const reg = details.registration || {};
  $("profileRegistrationBox").innerHTML = reg.status || reg.authority ? `<p><strong>${escapeHtml(reg.status || "Registration")}</strong></p><p class="sectionHelp">${escapeHtml(reg.authority || "Authority not listed")}</p>` : `<p class="sectionHelp">No registration details listed.</p>`;
  $("profileExitExamBox").innerHTML = details.medical_exit_exam?.status ? `<p><strong>${escapeHtml(details.medical_exit_exam.status)}</strong></p>` : `<p class="sectionHelp">No Medical Exit Examination details listed.</p>`;
  $("profileTrainingBox").innerHTML = (details.training || []).length ? details.training.map((item) => `<span class="softTag">${escapeHtml(item)}</span>`).join("") : `<p class="sectionHelp">No training listed.</p>`;
  $("profileSkillsBox").innerHTML = (details.skills || []).length ? details.skills.map((group) => `
    <div class="skillGroup"><h4>${escapeHtml(group.group)}</h4><div class="tagGrid">${(group.items || []).map((item) => `<span class="softTag">${escapeHtml(item)}</span>`).join("")}</div></div>`).join("") : `<p class="sectionHelp">No skills listed.</p>`;
  $("profileLanguagesBox").innerHTML = renderSimpleList((details.languages || []).map((item) => `${item.name}${item.level ? ` — ${item.level}` : ""}`));
}

function renderSimpleList(items) {
  return items && items.length ? `<ul class="cleanList">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p class="sectionHelp">Not listed.</p>`;
}

function statusPillClass(status) {
  if (status === "Verified") return "ready_to_apply";
  if (status === "Needs verification") return "needs_verification";
  return "not_eligible";
}

function renderProfileReview(review) {
  const box = $("profileReview");
  if (!review || !review.fields || !review.fields.length) {
    box.innerHTML = `<p class="sectionHelp">No profile loaded yet.</p>`;
    return;
  }
  const draftBanner = review.is_draft
    ? `<div class="notice warn">Draft profile — review every field before scanning or applying. ${escapeHtml(review.draft_note || "")}</div>`
    : "";
  const rows = review.fields.map((field) => {
    const isVerified = field.status === "Verified";
    const helper = isVerified ? "Ready for application matching." : "Needs your confirmation before it can support applications.";
    return `
      <div class="reviewRow">
        <div>
          <strong>${escapeHtml(field.label)}</strong>
          <p>${escapeHtml(helper)}</p>
        </div>
        <div class="reviewActions">
          <span class="statusBadge ${statusPillClass(field.status)}">${escapeHtml(field.status)}</span>
          ${!isVerified && field.confirm_field ? `<button class="secondary smallButton" data-action="confirm-field" data-field="${escapeAttr(field.confirm_field)}">Mark verified</button>` : ""}
        </div>
      </div>`;
  }).join("");
  box.innerHTML = draftBanner + rows;
}

function renderSettings() {
  const summary = state.profile?.summary || {};
  const settings = state.settings || {};
  $("settingsJobSearch").innerHTML = `
    <p class="sectionHelp">Preferred locations</p>
    ${renderSimpleList(summary.locations || [])}
    <p class="sectionHelp">Relevant roles</p>
    ${renderSimpleList(summary.roles || [])}`;
  $("settingsApplications").innerHTML = `
    <p>CV and cover letters are generated for review only.</p>
    <p class="sectionHelp">No email or form is submitted automatically.</p>`;
  $("settingsSources").innerHTML = renderSimpleList((settings.sources || []).map((source) => `${source.name} — ${source.active ? "Enabled" : "Disabled"}`));
  $("settingsPrivacy").innerHTML = `
    <p><strong>Check GitHub privacy before adding personal details.</strong> Your canonical profile is Git-tracked. If the repository is Public, profile.yaml and its Git history may be visible to anyone.</p>
    <p class="sectionHelp">Set your GitHub repository to Private and review earlier published copies. The local-only dashboard does not undo GitHub exposure.</p>
    <p class="sectionHelp">Generated documents remain local and are not submitted automatically.</p>`;
}

function renderScanRecommendations(scan) {
  // The scan's own authoritative recommendation collection — the exact list
  // the summary counter above counted (never recomputed in the browser).
  const entries = Array.isArray(scan?.recommendations) ? scan.recommendations : [];
  if (!entries.length) return "";
  const rows = entries.map((entry, index) => `
    <p class="sectionHelp">${index + 1}. ${escapeHtml(entry.title || "Untitled vacancy")} — ${escapeHtml(entry.company || "")} · ${escapeHtml(readinessValue(entry) || "Needs review")}</p>`).join("");
  return `<div class="sectionHelp" aria-label="Recommendations from this scan">${rows}</div>`;
}

function renderAdvanced() {
  const scan = state.lastScan;
  const reports = scan?.source_reports || [];
  if (!scan) {
    $("advancedSources").innerHTML = `<p class="sectionHelp">No scan has run in this browser session.</p>`;
    $("advancedScan").innerHTML = `<p><strong>Last scan:</strong> Not run</p><p class="sectionHelp">Run Find Jobs to record source connectivity and scan results.</p>`;
    $("advancedFailures").innerHTML = `<p class="sectionHelp">No failures recorded in this browser session.</p>`;
  } else {
    $("advancedSources").innerHTML = reports.map((source) => `
      <div class="sourceRow">
        <strong>${escapeHtml(source.name)}</strong>
        <span class="statusBadge ${statusClass(source.status || (source.ok ? "SCANNED" : "UNAVAILABLE"))}">${escapeHtml(scanStatusLabel(source.status || (source.ok ? "SCANNED" : "UNAVAILABLE")))}</span>
        <p>${escapeHtml(source.pages_requested || 0)} pages requested · ${escapeHtml(source.pages_succeeded || 0)} succeeded · ${escapeHtml(source.pages_failed || 0)} failed · ${escapeHtml(source.pagination_stop_reason || "UNKNOWN")}</p>
        ${source.source_listings_reported !== null && source.source_listings_reported !== undefined ? `<p class="sectionHelp">Source reports ${escapeHtml(source.source_listings_reported)} listings</p>` : ""}
        <p class="sectionHelp">${escapeHtml(sourceSummaryLine(source))}</p>
        <p class="sectionHelp">Details: ${escapeHtml(source.detail_pages_attempted || 0)} attempted / ${escapeHtml(source.detail_pages_succeeded || 0)} succeeded / ${escapeHtml(source.detail_pages_failed || 0)} failed · ${escapeHtml(source.listing_fallback_used || 0)} listing fallbacks</p>
        ${source.source_url ? `<p class="sectionHelp">Official source: ${escapeHtml(source.source_url)}</p>` : ""}
        ${source.timestamp ? `<p class="sectionHelp">Checked ${escapeHtml(source.timestamp)}</p>` : ""}
      </div>`).join("") || `<p class="sectionHelp">No source report available.</p>`;
    const returnedJobs = scan.job_count ?? scan.jobs?.length ?? 0;
    const total = scan.summary || {};
    $("advancedScan").innerHTML = `
      <p><strong>Status:</strong> ${escapeHtml(friendlyStatus(scan.status))}</p>
      <p><strong>Sources:</strong> ${escapeHtml(total.sources_attempted || 0)} attempted · ${escapeHtml(total.sources_scanned || 0)} scanned · ${escapeHtml(total.sources_partial || 0)} partial · ${escapeHtml(total.sources_unavailable || 0)} unavailable</p>
      <p><strong>Pages:</strong> ${escapeHtml(total.pages_requested || 0)} requested · ${escapeHtml(total.pages_succeeded || 0)} succeeded · ${escapeHtml(total.pages_failed || 0)} failed</p>
      <p><strong>Lifecycle:</strong> ${escapeHtml(total.listings_seen || 0)} listings · ${escapeHtml(total.listing_parse_failures || 0)} parse failures · ${escapeHtml(total.vacancies_parsed || 0)} parsed · ${escapeHtml(total.not_processed_due_to_budget || 0)} budget-deferred</p>
      <p><strong>Outcomes:</strong> ${escapeHtml(total.duplicates_removed || 0)} duplicates · ${escapeHtml(total.expired_excluded || 0)} expired · ${escapeHtml(total.irrelevant_excluded || 0)} irrelevant · ${escapeHtml(total.incompatible_role_classification_excluded || 0)} incompatible · ${escapeHtml(total.source_validation_excluded || 0)} source-invalid · ${escapeHtml(returnedJobs)} retained</p>
      <p><strong>Routes:</strong> ${escapeHtml(total.application_routes_found || 0)} found · ${escapeHtml(total.application_routes_unavailable || 0)} unavailable</p>
      <p><strong>Recommended from this scan:</strong> ${escapeHtml(total.recommended_from_scan || 0)} · ${escapeHtml(total.ready_to_apply_from_scan || 0)} ready · ${escapeHtml(total.needs_verification_from_scan || 0)} needs verification · ${escapeHtml(total.not_eligible_from_scan || 0)} not eligible</p>
      ${renderScanRecommendations(scan)}`;
    const failedReports = reports.filter((source) => !source.ok || source.error);
    $("advancedFailures").innerHTML = failedReports.length
      ? failedReports.map((source) => `<div class="sourceRow"><strong>${escapeHtml(source.name)}</strong><p>${escapeHtml(source.error || "Source returned no successful response.")}</p></div>`).join("")
      : `<p class="sectionHelp">No source failures recorded.</p>`;
  }
  $("advancedHealth").innerHTML = `
    <p><strong>Backend:</strong> authoritative for matching, verification, documents, and application safety.</p>
    <p><strong>Last scan:</strong> ${escapeHtml(scan?.status ? friendlyStatus(scan.status) : "Not run")}</p>
    <p class="sectionHelp">Advanced diagnostics are read-only and do not change matching or application decisions.</p>`;
}

function renderAll() {
  renderProfileIdentity();
  renderMetrics();
  renderScanSummary();
  renderJobLists();
  renderApplications();
  renderProfileDetails();
  renderProfileReview(state.profileReview);
  renderSettings();
  renderAdvanced();
  renderNextStep();
  renderAlerts();
  renderMonitoringSchedule();
}

function jobById(id) {
  // The selected detail drawer was refreshed from the authoritative record.
  // Cached first-page listings may still contain a stale draft/recipient.
  return (String(state.selectedJob?.id) === String(id) ? state.selectedJob : null)
    || state.jobs.find((job) => String(job.id) === String(id))
    || state.applications.find((job) => String(job.id) === String(id))
    || state.recommended.find((job) => String(job.id) === String(id))
    || null;
}

async function openJobById(id, mode = "details") {
  try {
    // Always refresh the official record and support old alert-linked listings.
    const job = await apiJson(`/api/jobs/${encodeURIComponent(id)}`);
    if (job) openDrawer(job, mode);
    else setStatus("Vacancy record not found.", "warn");
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function loadMoreJobs() {
  try {
    const data = await apiJson(`/api/jobs?limit=100&offset=${state.jobs.length}`);
    state.jobs.push(...data.jobs);
    state.jobsMeta = data;
    renderMetrics();
    renderJobLists();
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function loadMoreApplications() {
  try {
    const data = await apiJson(`/api/applications?limit=100&offset=${state.applications.length}`);
    state.applications.push(...data.jobs);
    state.applicationsMeta = data;
    renderApplications();
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

function requirementSection(title, items, emptyText) {
  if (!items.length) return `<section class="detailSection"><h3>${escapeHtml(title)}</h3><p class="sectionHelp">${escapeHtml(emptyText)}</p></section>`;
  return `<section class="detailSection"><h3>${escapeHtml(title)}</h3><ul class="requirementList">${items.map((item) => `<li><strong>${escapeHtml(item.label || item.key)}</strong><span>${escapeHtml(item.explanation || "Assessment available.")}</span></li>`).join("")}</ul></section>`;
}

function renderApplicationMethod(job) {
  const method = applicationMethod(job);
  const email = applyEmail(job);
  const web = safeExternalUrl(webApplyUrl(job));
  const page = safeExternalUrl(vacancyPage(job));
  if (job.is_expired) {
    return `<div class="routePanel unavailable"><h3>Vacancy deadline passed</h3><p>This saved vacancy is no longer open for new application preparation. Confirm any reopening directly with the employer.</p>${page ? `<a class="button secondary" href="${escapeAttr(page)}" target="_blank" rel="noopener">View official vacancy</a>` : ""}</div>`;
  }
  if (job.status === "APPLIED_MANUALLY") {
    return `<div class="routePanel"><h3>Already recorded as applied</h3><p>Your manual application has been preserved. You can still review its prepared documents below.</p>${page ? `<a class="button secondary" href="${escapeAttr(page)}" target="_blank" rel="noopener">View official vacancy</a>` : ""}</div>`;
  }
  if (!canPrepareJob(job)) {
    return `<div class="routePanel unavailable"><h3>Application requires review</h3><p>The verified profile does not meet this vacancy's critical requirements. You can still inspect the official posting.</p>${page ? `<a class="button secondary" href="${escapeAttr(page)}" target="_blank" rel="noopener">View official vacancy</a>` : ""}</div>`;
  }
  if (method === "EMAIL" && email) {
    return `<div class="routePanel"><p class="microLabel">Apply by email</p><h3>${escapeHtml(email)}</h3><div class="cardActions">${emailDraftReady(job) ? `<button class="primary subtle" data-action="apply-email" data-job-id="${escapeAttr(job.id)}">Apply · Email with attachments</button>` : `<button class="primary subtle" data-action="prepare-job" data-job-id="${escapeAttr(job.id)}">Prepare email and files</button>`}<button class="secondary" data-action="copy-email" data-email="${escapeAttr(email)}">Copy email</button></div></div>`;
  }
  if (method === "WEB" && web) {
    return `<div class="routePanel"><p class="microLabel">Apply online</p><h3>Web application</h3><div class="cardActions"><a class="button primary subtle" href="${escapeAttr(web)}" target="_blank" rel="noopener">Open application</a><button class="secondary" data-action="prepare-job" data-job-id="${escapeAttr(job.id)}">Prepare package</button></div></div>`;
  }
  return `<div class="routePanel unavailable"><p class="microLabel">Application route unavailable</p><h3>No direct route found</h3><p>Open the official vacancy page and verify how to apply before proceeding.</p>${page ? `<a class="button secondary" href="${escapeAttr(page)}" target="_blank" rel="noopener">Official vacancy page</a>` : ""}</div>`;
}

function documentCard(label, path) {
  if (!path) return `<div class="documentCard"><div><strong>${escapeHtml(label)}</strong><span>NOT CREATED</span></div></div>`;
  return `<div class="documentCard"><div><strong>${escapeHtml(label)}</strong><span>READY FOR REVIEW</span></div><a class="button secondary" href="${escapeAttr(openFileUrl(path))}" target="_blank" rel="noopener">Open</a></div>`;
}

// Keep every usable format visible. PDF is best for visual review and
// submission; the editable Word document is for refinements; text is a
// portable, accessible copy. No generated document is ever sent by the app.
function documentBundleCard(label, formats) {
  const files = formats && typeof formats === "object" ? formats : {};
  const links = [];
  if (files.pdf) {
    links.push(`<a class="button secondary smallButton" href="${escapeAttr(openFileUrl(files.pdf))}" target="_blank" rel="noopener">Preview PDF</a>`);
    links.push(`<a class="button secondary smallButton" href="${escapeAttr(openFileUrl(files.pdf, true))}">Download PDF</a>`);
  }
  if (files.docx) links.push(`<a class="button secondary smallButton" href="${escapeAttr(openFileUrl(files.docx, true))}">Download Word</a>`);
  if (files.txt) links.push(`<a class="button secondary smallButton" href="${escapeAttr(openFileUrl(files.txt))}" target="_blank" rel="noopener">View text</a>`);
  return `<div class="documentCard documentBundle"><div><strong>${escapeHtml(label)}</strong><span>${links.length ? "Ready for your review · no application sent" : "NOT CREATED"}</span></div><div class="documentActions">${links.join("")}</div></div>`;
}

function artifactStatusLabel(path) {
  return path ? "READY FOR REVIEW" : "NOT CREATED";
}

function renderPackage(job) {
  const pkg = job.package || {};
  const paths = generatedPaths(job);
  const cvFormats = paths.tailored_cv || {};
  const coverFormats = paths.cover_letter || {};
  const cvPath = cvFormats.pdf || cvFormats.docx || cvFormats.txt;
  const coverPath = coverFormats.pdf || coverFormats.docx || coverFormats.txt;
  const packagePath = paths.application_package_txt;
  const email = pkg.email_draft;
  const reviewNotes = [...new Set([...(pkg.review_warnings || []), ...(job.documents?.review_warnings || [])])];
  if (!pkg.package_status && !paths.tailored_cv) {
    return `<section class="detailSection"><h3>Your application package</h3><p class="sectionHelp">NOT CREATED — no package has been prepared yet.</p></section>`;
  }
  const packageState = friendlyStatus(pkg.package_status || job.package_status || "NOT_CREATED");
  const stateNote = pkg.package_status === "NEEDS_USER_INPUT" ? "Required user input or verification remains." : pkg.package_status === "BLOCKED" ? "The authoritative eligibility state blocks this package." : "Generated files remain for human review only.";
  return `<section class="detailSection"><h3>Your application package</h3>
    <p class="sectionHelp"><strong>Package state: ${escapeHtml(packageState)}</strong> — ${escapeHtml(stateNote)}</p>
    <div class="packageStatus"><span>${escapeHtml(artifactStatusLabel(cvPath))}: Tailored CV</span><span>${escapeHtml(artifactStatusLabel(coverPath))}: Cover letter</span>${email ? `<span>${emailDraftReady(job) ? "READY FOR REVIEW" : "NOT READY"}: Email draft</span>` : ""}</div>
    <div class="documentGrid">
      ${documentBundleCard("Tailored CV", cvFormats)}
      ${documentBundleCard("Cover letter", coverFormats)}
      ${email ? `<div class="documentCard"><div><strong>Email application</strong><span>${emailDraftReady(job) ? "Review the unsent draft and employer-requested PDFs." : "This draft is not ready to use. Check the official route, deadline and outstanding requirements."}</span></div>${emailDraftReady(job) ? `<button class="primary" data-action="apply-email" data-job-id="${escapeAttr(job.id)}">Apply — Open email</button>` : ""}<button class="secondary" data-action="show-email-draft" data-job-id="${escapeAttr(job.id)}">Preview</button></div>` : ""}
      ${packagePath ? documentCard("Application instructions", packagePath) : ""}
      ${paths.application_data_checklist ? documentCard("Application checklist", paths.application_data_checklist) : ""}
    </div>
    ${reviewNotes.length ? `<div class="applicationReviewNotes" role="note"><strong>Review before applying</strong><ul>${reviewNotes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul></div>` : ""}
  </section>`;
}

function openDrawer(job, mode = "details") {
  state.selectedJob = job;
  const drawer = $("detailDrawer");
  const backdrop = $("drawerBackdrop");
  const met = requirementsByStatus(job, "Met");
  const needs = requirementsByStatus(job, "Needs verification");
  const notMet = requirementsByStatus(job, "Not met");
  $("drawerTitle").textContent = job.title || "Job details";
  $("drawerKicker").textContent = compactText(job.company, "Vacancy");
  $("drawerContent").innerHTML = `
    <div class="detailHero">
      <span class="statusBadge ${job.is_expired ? "expired" : statusClass(readinessValue(job))}">${escapeHtml(readinessLabel(job))}</span>
      <p>${escapeHtml(compactText(job.company, "Organization not listed"))} · ${escapeHtml(compactText(job.location, "Location not listed"))}</p>
      <div class="jobMetaRow"><span>Deadline: ${escapeHtml(deadline(job))}</span><span>${escapeHtml(methodDescription(job))}</span><span>${escapeHtml(sourceName(job))}</span></div>
    </div>
    ${job.is_expired ? `<p class="sectionHelp">The stated deadline for this saved vacancy has passed. Historical documents remain available, but preparing a new application is blocked unless a new official vacancy is published.</p>` : ""}
    <section class="detailSection"><h3>About the role</h3><p>${escapeHtml(compactText(job.description, "No role description is stored for this vacancy."))}</p></section>
    ${renderApplicationMethod(job)}
    ${renderPackage(job)}
    ${requirementSection("You meet", met, "No met requirements are listed yet.")}
    ${requirementSection("Needs verification", needs, "No open verification items.")}
    ${requirementSection("Does not match", notMet, "No hard mismatches identified.")}`;
  if (mode === "package") {
    $("drawerContent").scrollTop = 0;
  }
  drawer.setAttribute("aria-hidden", "false");
  backdrop.hidden = false;
  drawer.classList.add("open");
  backdrop.classList.add("open");
  $("closeDrawer").focus();
}

function closeDrawer() {
  const drawer = $("detailDrawer");
  const backdrop = $("drawerBackdrop");
  drawer.classList.remove("open");
  backdrop.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  backdrop.hidden = true;
}

function showEmailDraft(job) {
  const email = job.package?.email_draft;
  if (!email) return;
  $("drawerContent").innerHTML = `
    <section class="detailSection emailPreview"><h3>Email draft</h3>
      <p><strong>To:</strong> ${escapeHtml(email.to || "")}</p>
      <p><strong>Subject:</strong> ${escapeHtml(email.subject || "")}</p>
      <pre>${escapeHtml(email.body || "")}</pre>
      <div class="cardActions">${emailDraftReady(job) ? `<button class="primary subtle" data-action="apply-email" data-job-id="${escapeAttr(job.id)}">Open attached email draft</button>` : ""}<button class="secondary" data-action="copy-email-draft" data-job-id="${escapeAttr(job.id)}">Copy full draft</button><button class="secondary" data-action="copy-email" data-email="${escapeAttr(email.to || "")}">Copy address</button></div>
      <p class="sectionHelp">Apply prepares a real .eml email containing only the vacancy-required reviewed PDFs. Windows may open it in a desktop mail app; otherwise download and open the .eml manually. Check sender, recipient, subject and attachments, then press Send in your email client. No email has been sent yet.</p>
    </section>`;
  $("drawerTitle").textContent = "Email draft";
  $("drawerKicker").textContent = job.title || "Application package";
}

function switchTab(tab) {
  state.currentTab = tab;
  document.querySelectorAll(".navItem").forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === tab));
  const titles = {
    dashboard: ["Dashboard", "Overview"],
    recommended: ["Recommended", "Most relevant vacancies"],
    jobs: ["All Jobs", "Complete discovered vacancy list"],
    applications: ["Applications", "Track packages and manual submissions"],
    alerts: ["Alerts", "New matches and approaching deadlines"],
    profile: ["My Profile", "Professional profile"],
    settings: ["Settings", "Preferences"],
    advanced: ["Advanced", "Technical diagnostics"],
  };
  const [title, subtitle] = titles[tab] || titles.dashboard;
  $("pageTitle").textContent = title;
  $("pageSubtitle").textContent = subtitle;
  closeDrawer();
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.message || "Request failed");
  return data;
}

async function refresh() {
  setLoadingLists();
  const [recommended, jobs, applications, profile, details, review, settings, latestScan, alerts, monitorSchedule] = await Promise.all([
    apiJson("/api/recommended"),
    apiJson("/api/jobs?limit=100&offset=0"),
    apiJson("/api/applications?limit=100&offset=0"),
    apiJson("/api/profile"),
    apiJson("/api/profile/details"),
    apiJson("/api/profile/review"),
    apiJson("/api/settings"),
    apiJson("/api/scan/latest"),
    apiJson("/api/alerts"),
    apiJson("/api/monitor/schedule"),
  ]);
  state.recommended = recommended.jobs || [];
  state.recommendationContext = recommended.scan || null;
  state.recommendationOrigin = recommended.data_origin || "";
  state.jobs = jobs.jobs || [];
  state.jobsMeta = jobs;
  state.applications = applications.jobs || [];
  state.applicationsMeta = applications;
  state.profile = profile;
  state.profileDetails = details;
  state.profileReview = review;
  state.settings = settings;
  state.lastScan = latestScan.scan || state.lastScan;
  state.alerts = alerts;
  state.monitorSchedule = monitorSchedule;
  renderAll();
}

async function verifyBackup() {
  const input = $("backupVerifyFile");
  const output = $("backupVerifyResult");
  if (!input.files || !input.files[0]) {
    setStatus("Choose a previously downloaded Jobs-Finder ZIP backup first.", "warn");
    return;
  }
  const button = $("verifyBackupBtn");
  button.disabled = true;
  output.textContent = "Checking ZIP integrity and saved database…";
  try {
    const form = new FormData();
    form.append("file", input.files[0]);
    const report = await apiJson("/api/backup/verify", {method: "POST", body: form});
    output.textContent = `Verified ${report.files_verified} files · ${report.vacancies_saved} saved vacancies · ${report.applications_submitted_saved} submitted applications · SQLite integrity OK. No files were restored or changed.`;
    setStatus("Your selected backup passed its independent integrity check. Keep it private.", "ok");
  } catch (error) {
    output.textContent = "Verification failed. Do not depend on this backup until a healthy replacement has been exported.";
    setStatus(humanizeError(error.message), "error");
  } finally {
    button.disabled = false;
  }
}

async function exportBackup() {
  const button = $("exportBackupBtn");
  button.disabled = true;
  setStatus("Preparing a private backup of your saved jobs and documents…", "warn");
  try {
    const response = await fetch("/api/backup/export", {method: "POST"});
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.detail || "The backup could not be created.");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(jobs-finder-backup-[0-9-]+\.zip)"/);
    const filename = match?.[1] || "jobs-finder-backup.zip";
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = filename;
    document.body.appendChild(download);
    download.click();
    download.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 3000);
    setStatus("Backup prepared. Check your browser Downloads and keep the ZIP private.", "ok");
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  } finally {
    button.disabled = false;
  }
}

async function findJobs() {
  if (state.profile && state.profile.exists === false) {
    setStatus("Your canonical local profile is missing. Create profile.yaml before scanning for jobs; CV preview does not create it.", "error");
    switchTab("profile");
    return;
  }
  setStatus("Finding suitable opportunities…", "warn");
  $("advancedLog").textContent = "Scan running…";
  try {
    const data = await apiJson("/api/find", { method: "POST" });
    state.lastScan = data;
    $("advancedLog").textContent = JSON.stringify(data, null, 2);
    const okStatuses = new Set(["SCAN_COMPLETE", "NO_RELEVANT_JOBS_FOUND"]);
    const kind = okStatuses.has(data.status) ? "ok" : data.status === "PARTIAL_SCAN" ? "warn" : "error";
    const message = data.status === "SOURCES_UNAVAILABLE" ? "Job sources could not be reached. Details are available in Advanced." : (data.message || friendlyStatus(data.status));
    setStatus(message, kind);
    await refresh();
  } catch (error) {
    $("advancedLog").textContent = String(error.stack || error.message || error);
    setStatus(humanizeError(error.message), "error");
  }
}

async function prepareJob(id) {
  setStatus("Preparing application package…", "warn");
  try {
    const data = await apiJson(`/api/jobs/${encodeURIComponent(id)}/prepare`, { method: "POST" });
    $("advancedLog").textContent = JSON.stringify(data, null, 2);
    setStatus("Package prepared. Review the CV, cover letter, and instructions before applying.", "ok");
    await refresh();
    // Open the newly generated package even outside the first ledger page.
    await openJobById(id, "package");
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function applyByEmail(id) {
  const job = jobById(id);
  if (!job || !emailDraftReady(job)) {
    setStatus("The email package is not ready or its official application route has changed. Review the vacancy and prepare a current package first.", "warn");
    return;
  }
  const approved = window.confirm(
    "Open a REVIEWABLE, UNSENT email with the official recipient, subject, body and required PDF attachments?\n\n" +
    "Windows needs a desktop email application associated with .eml files. Otherwise download the attached email. Verify all details and press Send yourself."
  );
  if (!approved) return;
  try {
    const result = await apiJson("/api/jobs/" + encodeURIComponent(id) + "/open-email", {method: "POST"});
    setStatus(result.message || "Draft opened. No email has been sent.", "ok");
  } catch (error) {
    setStatus(humanizeError(error.message) + " Download the EML if you have no Windows mail app configured.", "error");
    const link = document.createElement("a");
    link.href = "/api/jobs/" + encodeURIComponent(id) + "/email-draft.eml";
    link.textContent = "Download unsent email with attachments (.eml)";
    link.className = "button secondary";
    const area = $("drawerContent");
    if (area) area.prepend(link);
  }
}

async function addVerifiedResponsibility(index) {
  const element = $("responsibility-" + index);
  const text = element?.value?.trim() || "";
  if (text.length < 30) {
    setStatus("Describe an actual job responsibility in at least 30 characters.", "warn");
    return;
  }
  const confirmed = window.confirm(
    "I personally confirm this responsibility is factual and belongs to the selected job.\n\n" +
    "Only genuine work details will be added to the verified profile and future applications."
  );
  if (!confirmed) return;
  try {
    await apiJson("/api/profile/experience/add-responsibility", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        source_index: Number(index),
        text,
        confirmation: "I personally confirm this responsibility is factual and belongs to this role",
      }),
    });
    await refresh();
    setStatus("Verified role detail saved. New CVs will include your stronger professional evidence.", "ok");
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function copyEmail(email) {
  try {
    await navigator.clipboard.writeText(email);
    setStatus("Email address copied.", "ok");
  } catch (error) {
    window.prompt("Copy email address:", email);
  }
}

async function copyEmailDraft(jobId) {
  const email = jobById(jobId)?.package?.email_draft;
  if (!email) {
    setStatus("The application email draft is not available.", "warn");
    return;
  }
  const text = `To: ${email.to || ""}\nSubject: ${email.subject || ""}\n\n${email.body || ""}`;
  try {
    await navigator.clipboard.writeText(text);
    setStatus("Full email draft copied. Check attachments before sending.", "ok");
  } catch (error) {
    window.prompt("Copy the full draft and check attachments before sending:", text);
  }
}

async function confirmField(field) {
  const body = {field};
  if (field.startsWith("language:")) {
    const name = field.split(":")[1];
    const level = window.prompt(`Confirm your ${name} proficiency level (for example Native, Fluent, Professional, Basic):`, "");
    if (!level || !level.trim()) {
      setStatus("Confirmation cancelled: a proficiency level is required.", "warn");
      return;
    }
    body.level = level.trim();
  }
  try {
    const data = await apiJson("/api/profile/confirm", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) });
    state.profileReview = data.review;
    setStatus("Profile fact marked verified.", "ok");
    await refresh();
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function importCv() {
  const input = $("cvFile");
  if (!input.files || !input.files[0]) {
    setStatus("Choose a CV file first.", "error");
    return;
  }
  const form = new FormData();
  form.append("file", input.files[0]);
  setStatus("Importing CV…", "warn");
  try {
    const data = await apiJson("/api/import-cv", { method: "POST", body: form });
    // Import is a request-local, unverified preview.  It must never replace
    // the canonical applicant state shown in My Profile.
    $("advancedLog").textContent = JSON.stringify(data.preview || data, null, 2);
    setStatus(data.message, "warn");
    await refresh();
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function generateMasterCv() {
  setStatus("Generating your position-neutral Master CV…", "warn");
  try {
    const data = await apiJson("/api/master-cv", { method: "POST" });
    const paths = data.documents || {};
    const cards = documentBundleCard("Position-neutral Master CV", paths);
    const warnings = (data.review_warnings || []).length
      ? `<p class="sectionHelp">Review notes: ${escapeHtml((data.review_warnings || []).join(" "))}</p>`
      : "";
    $("masterCvResult").innerHTML = `<div class="documentGrid">${cards}</div>${warnings}`;
    setStatus("Master CV generated. Review it before use; it is not submitted anywhere.", "ok");
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

async function markApplied(id) {
  const confirmation = window.prompt(`If you manually submitted this application, type APPLIED ${id}`) || "";
  try {
    const data = await apiJson(`/api/jobs/${encodeURIComponent(id)}/mark-applied`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({confirmation}),
    });
    setStatus(data.message, "ok");
    await refresh();
  } catch (error) {
    setStatus(humanizeError(error.message), "error");
  }
}

function handleAction(event) {
  const target = event.target.closest("[data-action], [data-tab-target]");
  if (!target) return;
  if (target.dataset.tabTarget) {
    switchTab(target.dataset.tabTarget);
    return;
  }
  const action = target.dataset.action;
  const id = target.dataset.jobId;
  if (action === "find-jobs") findJobs();
  if (action === "export-backup") exportBackup();
  if (action === "verify-backup") verifyBackup();
  if (action === "load-more-jobs") loadMoreJobs();
  if (action === "load-more-applications") loadMoreApplications();
  if (action === "mark-alert-read") markAlertRead(target.dataset.alertId);
  if (action === "read-all-alerts") markAllAlertsRead();
  if (action === "toggle-daily-check") changeDailyChecks(target.dataset.enabled === "true");
  if (action === "refresh-monitor-status") refresh().catch((error) => setStatus(humanizeError(error.message), "error"));
  if (action === "view-job") openJobById(id);
  if (action === "prepare-job") prepareJob(id);
  if (action === "apply-email") applyByEmail(id);
  if (action === "add-responsibility") addVerifiedResponsibility(target.dataset.roleIndex);
  if (action === "review-package") openJobById(id, "package");
  if (action === "show-email-draft") {
    const job = jobById(id);
    if (job) showEmailDraft(job);
  }
  if (action === "copy-email") copyEmail(target.dataset.email || "");
  if (action === "copy-email-draft") copyEmailDraft(id);
  if (action === "mark-applied") markApplied(id);
  if (action === "confirm-field") confirmField(target.dataset.field || "");
}

for (const button of document.querySelectorAll(".navItem")) {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
}

$("mainContent").addEventListener("click", handleAction);
$("detailDrawer").addEventListener("click", handleAction);
$("findJobs").addEventListener("click", findJobs);
$("importCvBtn").addEventListener("click", importCv);
$("masterCvBtn").addEventListener("click", generateMasterCv);
$("closeDrawer").addEventListener("click", closeDrawer);
$("drawerBackdrop").addEventListener("click", closeDrawer);
$("collapseSidebar").addEventListener("click", () => document.body.classList.toggle("sidebarCollapsed"));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDrawer();
});

setStatus("Ready. Run a scan when you want to look for new vacancies.");
refresh().catch((error) => setStatus(humanizeError(error.message), "error"));

// Keep the inbox current if Windows Task Scheduler finishes a daily scan
// while the local dashboard is already open. This is a lightweight local
// read; it never initiates discovery or creates a browser-side background job.
window.setInterval(async () => {
  try {
    const previous = Number(state.alerts?.unread_count || 0);
    state.alerts = await apiJson("/api/alerts");
    renderAlerts();
    if (Number(state.alerts.unread_count || 0) > previous) {
      setStatus("New job-search alerts are available in your inbox.", "ok");
    }
  } catch (_) {
    // Startup/offline errors are surfaced by the normal refresh path.
  }
}, 120000);
