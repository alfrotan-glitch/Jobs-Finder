"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

// Exercise shipped functions without needing a browser or external network.
const script = fs.readFileSync(path.resolve(__dirname, "../dashboard/static/app.js"), "utf8");
const bootstrap = 'for (const button of document.querySelectorAll(".navItem"))';
assert.ok(script.includes(bootstrap));
const calls = [];
const context = vm.createContext({
  URL, console, encodeURIComponent, document: {}, window: {},
  fetch: async (url) => {
    calls.push(url);
    return {ok: true, json: async () => ({id: "old-392", title: "Updated saved vacancy", metadata: {}})};
  },
});
vm.runInContext(script.slice(0, script.indexOf(bootstrap)), context);
const get = (name) => vm.runInContext(name, context);

test("untrusted links must have safe HTTP(S) schemes and no credentials", () => {
  for (const link of ["javascript:alert(1)", "data:text/html,1", "//example.org",
    "file:///C:/private", "https://person:password@example.org/apply",
    "https://example.org/\nscript"]) {
    assert.equal(get("safeExternalUrl")(link), "", link);
  }
  assert.equal(get("safeExternalUrl")("https://example.org/jobs?q=1"), "https://example.org/jobs?q=1");
});

test("unsafe web routes cannot become links or enabled application actions", () => {
  const job = {id: "x", metadata: {application_method: "WEB",
    apply_url: "javascript:alert(1)", vacancy_url: "data:text/html,bad"}};
  assert.equal(get("directApplicationRouteAvailable")(job), false);
  const html = get("renderApplicationMethod")(job);
  assert.match(html, /Application route unavailable/);
  assert.doesNotMatch(html, /href=/);
});

test("authoritative refreshed application details take priority over old saved drafts", () => {
  const job = {metadata: {apply_email: "new@example.org", vacancy_url: "https://example.org/new"},
    package: {apply_email: "old@example.org", official_vacancy_page: "https://example.org/old"}};
  assert.equal(get("applyEmail")(job), "new@example.org");
  assert.equal(get("vacancyPage")(job), "https://example.org/new");
});

test("older alert-linked records remain available to drawer actions", async () => {
  const state = get("state");
  state.jobs = [];
  state.applications = [];
  state.recommended = [];
  vm.runInContext("openDrawer = (job) => { state.selectedJob = job; }", context);
  await get('openJobById("old-392")');
  assert.equal(calls.at(-1), "/api/jobs/old-392");
  assert.equal(get("jobById")("old-392").title, "Updated saved vacancy");
  assert.equal(get("jobById")("unknown"), null);
});

test("list records are refreshed from source before showing stale details", async () => {
  const state = get("state");
  state.jobs = [{id: "old-392", title: "Stale title"}];
  await get('openJobById("old-392")');
  assert.equal(state.selectedJob.title, "Updated saved vacancy");
});

test("only fully ready official email packages can show an Apply action", () => {
  const job = {id: "x", metadata: {application_method: "EMAIL", apply_email: "jobs@example.org"},
    package: {route_type: "email", package_status: "READY_FOR_REVIEW",
      email_draft: {to: "jobs@example.org", body: "Application"}}};
  assert.equal(get("emailDraftReady")(job), true);
  assert.match(get("renderPackage")(job), /data-action="apply-email"/);
  for (const modification of [
    {is_expired: true},
    {status: "APPLIED_MANUALLY"},
    {metadata: {application_method: "WEB", apply_url: "https://example.org/apply"}},
    {package: {...job.package, package_status: "NEEDS_USER_INPUT"}},
    {package: {...job.package, missing_items: ["medical registration"]}},
  ]) {
    const unsafe = {...job, ...modification};
    assert.equal(get("emailDraftReady")(unsafe), false);
    assert.doesNotMatch(get("renderPackage")(unsafe), /data-action="apply-email"/);
  }
});

test("refreshed drawer data wins over an older cached listing for Apply actions", () => {
  const state = get("state");
  state.jobs = [{id: "old-392", title: "Cached obsolete job",
    metadata: {application_method: "EMAIL", apply_email: "old@example.org"}}];
  state.selectedJob = {id: "old-392", title: "Refreshed current job",
    metadata: {application_method: "WEB", apply_url: "https://example.org/apply"}};
  assert.equal(get("jobById")("old-392").title, "Refreshed current job");
  assert.equal(get("applicationMethod")(get("jobById")("old-392")), "WEB");
});

test("one preparation action is offered per vacancy and incompatible roles are blocked", () => {
  const base = {id: "medical-1", readiness: "READY_TO_APPLY",
    metadata: {application_method: "EMAIL", apply_email: "hr@example.org"}};
  const route = get("renderApplicationMethod")(base);
  assert.equal((route.match(/data-action="prepare-job"/g) || []).length, 1);
  const blocked = {...base, readiness: "NOT_ELIGIBLE"};
  assert.equal(get("canPrepareJob")(blocked), false);
  assert.doesNotMatch(get("renderApplicationMethod")(blocked), /data-action="prepare-job"/);
  assert.doesNotMatch(get("jobCard")(blocked), /data-action="mark-applied"/);
  assert.doesNotMatch(get("jobCard")(blocked), /data-action="prepare-job"/);
});


test("private-reference backup link remains separate from public profile export", () => {
  assert.match(script, /\/api\/profile\/references\/export/);
  assert.match(script, /Download private references backup/);
  assert.match(script, /main ZIP backup and GitHub/);
});


test("saved packages expose actual regeneration instead of stale PDF downloads only", () => {
  const job = {
    id:"old-medical-coordinator", title:"Medical Coordinator", company:"Example NGO",
    status:"PACKAGE_READY",
    readiness:"READY_TO_APPLY",
    is_expired:false,
    package:{package_status:"READY_FOR_REVIEW", email_draft:{to:"hr@example.org",body:"Application"}},
    documents:{generated_paths:{tailored_cv:{pdf:"documents/applications/old.pdf"}}},
  };
  const html = get("renderPackage")(job);
  assert.match(html, /Regenerate CV, cover letter & email from current verified profile/);
  assert.match(html, /data-action="prepare-job"/);
  const applied = {...job, status:"APPLIED_MANUALLY"};
  assert.doesNotMatch(get("renderPackage")(applied), /Regenerate CV, cover letter/);
});


test("outdated employer CVs show regeneration required and hide old downloads", () => {
  const job = {
    id: "old-medical-coordinator",
    title: "Medical Coordinator",
    metadata: {application_method: "EMAIL", apply_email: "recruiting@example.org"},
    package_freshness: {current: false, reason: "old_cv_generator"},
    package: {
      package_status: "READY_FOR_REVIEW", route_type: "email", missing_items: [],
      email_draft: {to: "recruiting@example.org", body: "Old text"}
    },
    documents: {
      generated_paths: {
        tailored_cv: {pdf: "documents/applications/old.pdf"},
        cover_letter: {pdf: "documents/applications/old-letter.pdf"},
      },
    },
  };
  assert.equal(get("emailDraftReady")(job), false);
  const html = get("renderPackage")(job);
  assert.match(html, /REGENERATION REQUIRED/);
  assert.match(html, /OUTDATED DOCUMENTS/);
  assert.match(html, /Regenerate CV, cover letter & email/);
  assert.doesNotMatch(html, /Download PDF/);
  assert.doesNotMatch(html, /data-action="apply-email"/);
});
