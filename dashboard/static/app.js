const state = {
  jobs: [],
  recommended: [],
  recommendationContext: null,
  recommendationOrigin: "",
  profile: {},
  profileDetails: {},
  profileReview: {},
  settings: {},
  lastScan: null,
  currentTab: "dashboard",
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
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
  return (job.package?.application_method || job.metadata?.application_method || job.match?.facts?.application_method || job.application_method || "UNAVAILABLE").toUpperCase();
}

function applyEmail(job) {
  return job.package?.apply_email || job.metadata?.apply_email || job.match?.facts?.apply_email || job.match?.facts?.application_email || job.apply_email || "";
}

function webApplyUrl(job) {
  return job.package?.apply_url || job.metadata?.apply_url || job.match?.facts?.apply_url || job.match?.facts?.application_url || job.apply_url || "";
}

function vacancyPage(job) {
  return job.package?.official_vacancy_page || job.metadata?.vacancy_url || job.match?.facts?.vacancy_url || job.url || "";
}

function readinessValue(job) {
  return job.readiness || job.match?.readiness_status || "";
}

function readinessLabel(job) {
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
  return (method === "EMAIL" && Boolean(applyEmail(job))) || (method === "WEB" && Boolean(webApplyUrl(job)));
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

function openFileUrl(path) {
  return `/api/generated-file?path=${encodeURIComponent(path)}`;
}

function jobCard(job, {compact = false} = {}) {
  const readiness = readinessValue(job);
  const method = applicationMethod(job);
  const labels = requirementLabels(job, "Met", compact ? 3 : 5);
  const id = escapeAttr(job.id);
  const org = compactText(job.company, "Organization not listed");
  const location = compactText(job.location, "Location not listed");
  const isNotEligible = readiness === "NOT_ELIGIBLE";
  return `
    <article class="jobCard ${compact ? "compact" : ""}">
      <div class="jobCardHeader">
        <div class="jobTitleBlock">
          <h3>${escapeHtml(job.title || "Untitled vacancy")}</h3>
          <p>${escapeHtml(org)} · ${escapeHtml(location)}</p>
        </div>
        <span class="statusBadge ${statusClass(readiness)}">${escapeHtml(readinessLabel(job))}</span>
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
        ${!isNotEligible && directApplicationRouteAvailable(job) ? `<button class="primary subtle" data-action="prepare-job" data-job-id="${id}">${method === "EMAIL" ? "Prepare email" : "Prepare application"}</button>` : ""}
        ${packageExists(job) ? `<button class="secondary" data-action="review-package" data-job-id="${id}">Review package</button>` : ""}
        ${packageReadyForReview(job) && job.status !== "APPLIED_MANUALLY" ? `<button class="secondary" data-action="mark-applied" data-job-id="${id}">Mark applied</button>` : ""}
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
  const ready = state.jobs.filter((job) => readinessValue(job) === "READY_TO_APPLY").length;
  const applications = state.jobs.filter((job) => ["PACKAGE_READY", "PACKAGE_NEEDS_INPUT", "APPLIED_MANUALLY"].includes(job.status)).length;
  $("metricRecommended").textContent = state.recommended.length;
  $("metricJobs").textContent = state.jobs.length;
  $("metricReady").textContent = ready;
  $("metricApplications").textContent = applications;
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
  if (state.lastScan?.status === "SOURCES_UNAVAILABLE" || state.lastScan?.status === "PARTIAL_SCAN") {
    box.innerHTML = `
      <div class="nextStepIcon warn" aria-hidden="true">!</div>
      <h4>Job sources could not be reached</h4>
      <p>One or more configured job sources could not be contacted during the last scan. This does not mean there are no jobs.</p>
      <button class="secondary" data-tab-target="advanced">View details</button>`;
    return;
  }
  if (!state.jobs.length) {
    box.innerHTML = `
      <div class="nextStepIcon" aria-hidden="true">↻</div>
      <h4>Run a vacancy scan</h4>
      <p>Start with a scan to find suitable opportunities from the configured sources.</p>
      <button class="primary subtle" data-action="find-jobs">Find Jobs</button>`;
    return;
  }
  const ready = state.recommended.find((job) => readinessValue(job) === "READY_TO_APPLY");
  if (ready) {
    box.innerHTML = `
      <div class="nextStepIcon ok" aria-hidden="true">✓</div>
      <h4>Prepare the strongest application</h4>
      <p>${escapeHtml(ready.title)} is ready for review.</p>
      <button class="primary subtle" data-action="prepare-job" data-job-id="${escapeAttr(ready.id)}">Prepare application</button>`;
    return;
  }
  box.innerHTML = `
    <div class="nextStepIcon" aria-hidden="true">◦</div>
    <h4>Review open requirements</h4>
    <p>Some recommended jobs need verification before applying.</p>
    <button class="secondary" data-tab-target="recommended">Review recommendations</button>`;
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
  $("jobsList").innerHTML = state.jobs.length
    ? state.jobs.map((job) => jobCard(job)).join("")
    : sourceFailed
      ? emptyState("Job sources could not be reached", "This is a source connectivity problem, not a finding that no jobs exist.", sourceAction)
      : emptyState("No jobs yet", "Run a scan to populate this list with actionable vacancies.", `<button class="primary subtle" data-action="find-jobs">Run scan</button>`);
}

function renderApplications() {
  const counts = {
    FOUND: 0,
    REVIEWED: 0,
    PACKAGE: 0,
    APPLIED: 0,
  };
  for (const job of state.jobs) {
    if (job.status === "FOUND") counts.FOUND += 1;
    else if (["PACKAGE_READY", "PACKAGE_NEEDS_INPUT"].includes(job.status)) counts.PACKAGE += 1;
    else if (job.status === "APPLIED_MANUALLY") counts.APPLIED += 1;
    else counts.REVIEWED += 1;
  }
  $("stageFound").textContent = counts.FOUND;
  $("stageReviewed").textContent = counts.REVIEWED;
  $("stagePackage").textContent = counts.PACKAGE;
  $("stageApplied").textContent = counts.APPLIED;
  const applicationJobs = state.jobs.filter((job) => ["PACKAGE_READY", "PACKAGE_NEEDS_INPUT", "APPLIED_MANUALLY"].includes(job.status));
  $("applicationsList").innerHTML = applicationJobs.length
    ? applicationJobs.map((job) => jobCard(job)).join("")
    : emptyState("No application packages yet", "Prepare a package from a recommended vacancy to start tracking it here.");
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
    <p>Your profile stays in an ignored local file and is not committed by the app.</p>
    <p class="sectionHelp">Generated documents are kept locally for review and are not submitted by the system.</p>`;
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
}

function jobById(id) {
  return state.jobs.find((job) => String(job.id) === String(id)) || state.recommended.find((job) => String(job.id) === String(id));
}

function requirementSection(title, items, emptyText) {
  if (!items.length) return `<section class="detailSection"><h3>${escapeHtml(title)}</h3><p class="sectionHelp">${escapeHtml(emptyText)}</p></section>`;
  return `<section class="detailSection"><h3>${escapeHtml(title)}</h3><ul class="requirementList">${items.map((item) => `<li><strong>${escapeHtml(item.label || item.key)}</strong><span>${escapeHtml(item.explanation || "Assessment available.")}</span></li>`).join("")}</ul></section>`;
}

function renderApplicationMethod(job) {
  const method = applicationMethod(job);
  const email = applyEmail(job);
  const web = webApplyUrl(job);
  const page = vacancyPage(job);
  if (method === "EMAIL" && email) {
    return `<div class="routePanel"><p class="microLabel">Apply by email</p><h3>${escapeHtml(email)}</h3><div class="cardActions"><a class="button primary subtle" href="mailto:${escapeAttr(email)}">Open email</a><button class="secondary" data-action="copy-email" data-email="${escapeAttr(email)}">Copy email</button><button class="secondary" data-action="prepare-job" data-job-id="${escapeAttr(job.id)}">Prepare email</button></div></div>`;
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

function artifactStatusLabel(path) {
  return path ? "READY FOR REVIEW" : "NOT CREATED";
}

function renderPackage(job) {
  const pkg = job.package || {};
  const paths = generatedPaths(job);
  const cvPath = paths.tailored_cv?.pdf || paths.tailored_cv?.txt;
  const coverPath = paths.cover_letter?.pdf || paths.cover_letter?.txt;
  const packagePath = paths.application_package_txt;
  const email = pkg.email_draft;
  if (!pkg.package_status && !paths.tailored_cv) {
    return `<section class="detailSection"><h3>Your application package</h3><p class="sectionHelp">NOT CREATED — no package has been prepared yet.</p></section>`;
  }
  const packageState = friendlyStatus(pkg.package_status || job.package_status || "NOT_CREATED");
  const stateNote = pkg.package_status === "NEEDS_USER_INPUT" ? "Required user input or verification remains." : pkg.package_status === "BLOCKED" ? "The authoritative eligibility state blocks this package." : "Generated files remain for human review only.";
  return `<section class="detailSection"><h3>Your application package</h3>
    <p class="sectionHelp"><strong>Package state: ${escapeHtml(packageState)}</strong> — ${escapeHtml(stateNote)}</p>
    <div class="packageStatus"><span>${escapeHtml(artifactStatusLabel(cvPath))}: Tailored CV</span><span>${escapeHtml(artifactStatusLabel(coverPath))}: Cover letter</span>${email ? `<span>READY FOR REVIEW: Email draft</span>` : ""}</div>
    <div class="documentGrid">
      ${documentCard("Tailored CV", cvPath)}
      ${documentCard("Cover letter", coverPath)}
      ${email ? `<div class="documentCard"><div><strong>Email draft</strong><span>READY FOR REVIEW — manual sending only</span></div><button class="secondary" data-action="show-email-draft" data-job-id="${escapeAttr(job.id)}">Open</button></div>` : ""}
      ${packagePath ? documentCard("Application instructions", packagePath) : ""}
    </div>
  </section>`;
}

function openDrawer(job, mode = "details") {
  const drawer = $("detailDrawer");
  const backdrop = $("drawerBackdrop");
  const met = requirementsByStatus(job, "Met");
  const needs = requirementsByStatus(job, "Needs verification");
  const notMet = requirementsByStatus(job, "Not met");
  $("drawerTitle").textContent = job.title || "Job details";
  $("drawerKicker").textContent = compactText(job.company, "Vacancy");
  $("drawerContent").innerHTML = `
    <div class="detailHero">
      <span class="statusBadge ${statusClass(readinessValue(job))}">${escapeHtml(readinessLabel(job))}</span>
      <p>${escapeHtml(compactText(job.company, "Organization not listed"))} · ${escapeHtml(compactText(job.location, "Location not listed"))}</p>
      <div class="jobMetaRow"><span>Deadline: ${escapeHtml(deadline(job))}</span><span>${escapeHtml(methodDescription(job))}</span><span>${escapeHtml(sourceName(job))}</span></div>
    </div>
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
      <div class="cardActions"><a class="button primary subtle" href="mailto:${escapeAttr(email.to || "")}">Open email</a><button class="secondary" data-action="copy-email" data-email="${escapeAttr(email.to || "")}">Copy email</button></div>
      <p class="sectionHelp">Prepared for review only. The system has not sent this email.</p>
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
  const [recommended, jobs, profile, details, review, settings, latestScan] = await Promise.all([
    apiJson("/api/recommended"),
    apiJson("/api/jobs"),
    apiJson("/api/profile"),
    apiJson("/api/profile/details"),
    apiJson("/api/profile/review"),
    apiJson("/api/settings"),
    apiJson("/api/scan/latest"),
  ]);
  state.recommended = recommended.jobs || [];
  state.recommendationContext = recommended.scan || null;
  state.recommendationOrigin = recommended.data_origin || "";
  state.jobs = jobs.jobs || [];
  state.profile = profile;
  state.profileDetails = details;
  state.profileReview = review;
  state.settings = settings;
  state.lastScan = latestScan.scan || state.lastScan;
  renderAll();
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
    const job = jobById(id);
    if (job) openDrawer(job, "package");
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
    const cards = ["pdf", "docx", "txt"]
      .filter((kind) => paths[kind])
      .map((kind) => documentCard(`Master CV (${kind.toUpperCase()})`, paths[kind]))
      .join("");
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
  if (action === "view-job") {
    const job = jobById(id);
    if (job) openDrawer(job);
  }
  if (action === "prepare-job") prepareJob(id);
  if (action === "review-package") {
    const job = jobById(id);
    if (job) openDrawer(job, "package");
  }
  if (action === "show-email-draft") {
    const job = jobById(id);
    if (job) showEmailDraft(job);
  }
  if (action === "copy-email") copyEmail(target.dataset.email || "");
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
