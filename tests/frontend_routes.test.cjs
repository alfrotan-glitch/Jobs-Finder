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
