function mrjobs() {
  return {
    view: "recommended",
    needsSetup: false,
    loading: false,
    discovering: false,
    preparing: {},
    notification: "",
    notificationType: "success",

    jobs: [],
    jobFilter: "recommended",
    recommended: [],
    applications: [],
    stats: {},
    watcherSummary: { counts: {}, unread_notifications: 0, last_scan: null },
    watcherNotifications: [],
    scanAudits: [],
    schedulerStatus: { running: false, jobs: [], settings: {} },
    sourceRegistryStatus: { counts: {}, active: [], errors: [] },
    profile: {},
    evidence: {},
    selectedJob: null,
    selectedAnalysis: null,
    selectedDocs: null,

    setupData: defaultMedicalProfile(),
    resumeUploading: false,
    resumeName: "Primary CV",

    async init() {
      await this.loadProfile();
      if (this.needsSetup) return;
      await Promise.all([this.refreshAll(), this.loadEvidence()]);
    },

    async refreshAll() {
      await Promise.all([
        this.loadRecommended(),
        this.loadJobs(),
        this.loadApplications(),
        this.loadStats(),
        this.loadWatcherSummary(),
      ]);
    },

    async loadProfile() {
      try {
        const res = await fetch("/api/profile");
        const data = await res.json();
        if (data.needs_setup) {
          this.needsSetup = true;
          return;
        }
        this.profile = mergeDefaults(defaultMedicalProfile(), data || {});
      } catch (err) {
        this.notify("Could not load profile: " + err.message, "error");
      }
    },

    async loadEvidence() {
      try {
        const res = await fetch("/api/profile/evidence");
        const data = await res.json();
        this.evidence = data.evidence || {};
      } catch (_) {}
    },

    async saveProfile() {
      try {
        const res = await fetch("/api/profile", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.profile),
        });
        if (!res.ok) throw new Error(await res.text());
        this.profile = await res.json();
        await this.loadEvidence();
        this.notify("Profile saved.");
      } catch (err) {
        this.notify("Profile save failed: " + err.message, "error");
      }
    },

    async completeSetup() {
      try {
        const res = await fetch("/api/setup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(this.setupData),
        });
        if (!res.ok) throw new Error(await res.text());
        this.needsSetup = false;
        await this.init();
        this.notify("Setup complete. Add your CV in My Profile if you have not uploaded it yet.");
      } catch (err) {
        this.notify("Setup failed: " + err.message, "error");
      }
    },

    async loadRecommended() {
      try {
        const res = await fetch("/api/recommended?limit=25");
        const data = await res.json();
        this.recommended = (data.jobs || []).map(normalizeJob);
      } catch (err) {
        this.notify("Could not load recommended jobs: " + err.message, "error");
      }
    },

    async loadJobs() {
      try {
        const res = await fetch("/api/watch/jobs?active_only=true&limit=300");
        const data = await res.json();
        this.jobs = (data.jobs || []).map(normalizeJob);
      } catch (_) {
        try {
          const res = await fetch("/api/jobs?limit=200&sort_by=discovered_at&sort_order=desc");
          const data = await res.json();
          this.jobs = (data.jobs || []).map(normalizeJob).filter((j) => !isClosedOrExpired(j));
        } catch (_) {}
      }
    },

    async loadApplications() {
      try {
        const statuses = ["prepared", "review", "opened", "submitted", "applied", "interviewing", "offer", "rejected", "withdrawn"];
        const res = await fetch("/api/jobs?limit=300&sort_by=discovered_at&sort_order=desc");
        const data = await res.json();
        this.applications = (data.jobs || []).map(normalizeJob).filter((j) => statuses.includes(j.status));
      } catch (_) {}
    },

    async loadStats() {
      try {
        const res = await fetch("/api/stats");
        this.stats = await res.json();
      } catch (_) {}
    },

    async loadWatcherSummary() {
      try {
        const [summaryRes, notificationRes, scansRes, schedulerRes, registryRes] = await Promise.all([
          fetch("/api/watch/summary"),
          fetch("/api/watch/notifications?limit=10"),
          fetch("/api/watch/scans?limit=10"),
          fetch("/api/scheduler/status"),
          fetch("/api/system/source-registry"),
        ]);
        this.watcherSummary = await summaryRes.json();
        this.watcherNotifications = ((await notificationRes.json()).notifications || []);
        this.scanAudits = ((await scansRes.json()).scans || []);
        this.schedulerStatus = await schedulerRes.json();
        this.sourceRegistryStatus = await registryRes.json();
      } catch (_) {}
    },

    async discover() {
      this.discovering = true;
      this.notify("Discovery started. This may take a few minutes.", "info");
      try {
        const res = await fetch("/api/discover", { method: "POST" });
        if (!res.ok) throw new Error(await res.text());
        setTimeout(() => this.pollDiscovery(), 2500);
      } catch (err) {
        this.discovering = false;
        this.notify("Discovery could not start: " + err.message, "error");
      }
    },

    async pollDiscovery(attempt = 0) {
      await this.refreshAll();
      if (attempt < 18) {
        setTimeout(() => this.pollDiscovery(attempt + 1), 5000);
      } else {
        this.discovering = false;
        this.notify("Discovery finished or is still running in the background. Refresh if needed.", "success");
      }
    },

    async openJob(job) {
      this.selectedJob = job;
      this.selectedDocs = null;
      this.selectedAnalysis = job.match || null;
      if (!this.selectedAnalysis) await this.loadAnalysis(job);
    },

    async loadAnalysis(job) {
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/analysis`);
        if (!res.ok) throw new Error(await res.text());
        this.selectedAnalysis = await res.json();
        job.match = this.selectedAnalysis;
      } catch (err) {
        this.notify("Analysis failed: " + err.message, "error");
      }
    },

    async prepare(job) {
      this.preparing[job.id] = true;
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/tailor`, { method: "POST" });
        if (!res.ok) throw new Error(await res.text());
        this.notify("Preparing CV and cover letter. Please wait a moment.", "info");
        setTimeout(() => this.loadDocs(job), 3000);
        await this.refreshAll();
      } catch (err) {
        this.notify("Could not prepare documents: " + err.message, "error");
      } finally {
        this.preparing[job.id] = false;
      }
    },

    async loadDocs(job) {
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/tailor`);
        if (!res.ok) throw new Error(await res.text());
        this.selectedDocs = await res.json();
        if (this.selectedDocs && (this.selectedDocs.cover_letter || this.selectedDocs.tailored_cv_text)) {
          this.notify("Documents ready for review.");
        }
      } catch (err) {
        this.notify("Could not load documents: " + err.message, "error");
      }
    },

    async fillReview(job) {
      try {
        const res = await fetch(`/api/apply/${encodeURIComponent(job.id)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dry_run: true }),
        });
        if (!res.ok) throw new Error(await res.text());
        this.notify("Review-only filling started. The browser will stop before final submission.", "info");
      } catch (err) {
        this.notify("Could not start form assistance: " + err.message, "error");
      }
    },

    async openApplication(job) {
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/open`, { method: "POST" });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        window.open(data.url, "_blank", "noopener");
        await this.refreshAll();
      } catch (err) {
        this.notify("Could not open application: " + err.message, "error");
      }
    },

    async confirmSubmitted(job) {
      const phrase = `SUBMITTED ${job.id}`;
      const typed = prompt(`Only record this after you personally submitted the application. Type exactly:\n${phrase}`);
      if (typed !== phrase) return;
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}/confirm-submitted`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmation: phrase }),
        });
        if (!res.ok) throw new Error(await res.text());
        this.notify("Application recorded as submitted.");
        await this.refreshAll();
      } catch (err) {
        this.notify("Could not record submission: " + err.message, "error");
      }
    },

    async updateStatus(job, status) {
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(job.id)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        });
        if (!res.ok) throw new Error(await res.text());
        await this.refreshAll();
      } catch (err) {
        this.notify("Status update failed: " + err.message, "error");
      }
    },

    async uploadResume(input) {
      const file = input?.files?.[0];
      if (!file) return;
      this.resumeUploading = true;
      try {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("name", this.resumeName || "Primary CV");
        const res = await fetch("/api/resumes", { method: "POST", body: fd });
        if (!res.ok) throw new Error(await res.text());
        input.value = "";
        await this.loadProfile();
        await this.loadEvidence();
        this.notify("CV uploaded and selected as evidence source.");
      } catch (err) {
        this.notify("CV upload failed: " + err.message, "error");
      } finally {
        this.resumeUploading = false;
      }
    },

    setView(name) {
      this.view = name;
      this.selectedJob = null;
    },

    tableFor(job) {
      const match = job.match || parseMaybeJSON(job.match_json) || job.last_matching_result || {};
      return match.requirement_matches || [];
    },

    matchReasons(job) {
      return this.tableFor(job)
        .filter((item) => item.status === "Met" && !["closing_date", "application_destination", "application_subject"].includes(item.key))
        .slice(0, 4)
        .map((item) => `${item.label} met`);
    },

    routeLabel(job) {
      const route = job.application_route || job.apply_url || job.application_email || "";
      if (!route) return "Application route needs verification";
      if (route.startsWith("mailto:") || route.includes("@")) return "Email application";
      if (route.includes("docs.google.com/forms") || route.includes("forms.gle")) return "Google Form";
      if (route.includes("oraclecloud.com")) return "Employer careers portal";
      if (route.includes("odoo.com")) return "Employer profile/application page";
      return "Online application";
    },

    readinessLabel(job) {
      const value = job.readiness_status || job.watcher_readiness_status || job.status || "";
      if (value === "READY_TO_APPLY") return "Ready to Apply";
      if (value === "NEEDS_VERIFICATION") return "Needs Verification";
      if (value === "NOT_ELIGIBLE") return "Not Eligible";
      return statusLabel(value);
    },

    statusLabel,

    isClosingSoon,

    filteredJobs() {
      const jobs = this.jobs.filter((job) => !isClosedOrExpired(job));
      if (this.jobFilter === "recommended") return this.recommended;
      if (this.jobFilter === "ready") return jobs.filter((job) => job.readiness_status === "READY_TO_APPLY");
      if (this.jobFilter === "verify") return jobs.filter((job) => job.readiness_status === "NEEDS_VERIFICATION");
      if (this.jobFilter === "closing") return jobs.filter(isClosingSoon);
      if (this.jobFilter === "new") return jobs.filter((job) => job.last_change_type === "NEW" || job.watcher_change_type === "NEW");
      if (this.jobFilter === "updated") return jobs.filter((job) => job.last_change_type === "UPDATED" || job.watcher_change_type === "UPDATED");
      return jobs;
    },

    evidenceCount(key) {
      return (this.evidence[key] || []).length;
    },

    addArray(path, value) {
      const val = (value || "").trim();
      if (!val) return "";
      const parts = path.split(".");
      let obj = this.profile;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!obj[parts[i]]) obj[parts[i]] = {};
        obj = obj[parts[i]];
      }
      const key = parts[parts.length - 1];
      if (!Array.isArray(obj[key])) obj[key] = [];
      if (!obj[key].includes(val)) obj[key].push(val);
      return "";
    },

    removeArray(path, index) {
      const arr = getPath(this.profile, path);
      if (Array.isArray(arr)) arr.splice(index, 1);
    },

    notify(message, type = "success") {
      this.notification = message;
      this.notificationType = type;
      clearTimeout(this._notifyTimer);
      this._notifyTimer = setTimeout(() => (this.notification = ""), 5000);
    },
  };
}

function normalizeJob(job) {
  const out = { ...job };
  out.id = out.id || out.canonical_id;
  out.company = out.company || out.organization;
  out.metadata = parseMaybeJSON(out.metadata) || out.metadata || {};
  out.match = parseMaybeJSON(out.match_json) || out.last_matching_result || null;
  out.priority_reasons = out.priority_reasons || parseMaybeJSON(out.watcher_priority_reasons_json) || [];
  out.source_urls = out.source_urls || parseMaybeJSON(out.watcher_source_urls_json) || out.metadata.source_urls || [];
  if (!out.priority && out.match) out.priority = out.match.priority;
  out.readiness_status = out.readiness_status || out.watcher_readiness_status || out.metadata.readiness_status || (out.match && out.match.readiness_status) || out.status;
  out.operational_priority = out.operational_priority || out.watcher_operational_priority || out.metadata.operational_priority || "";
  out.last_change_type = out.last_change_type || out.watcher_change_type || "";
  out.application_route = out.application_route || out.apply_url || out.application_email || out.metadata.application_email || out.metadata.application_url || "";
  const docs = parseMaybeJSON(out.documents_json) || parseMaybeJSON(out.tailored_resume) || {};
  out.documents = docs;
  out.tailored_cv_ready = Boolean(docs.tailored_cv_text || docs.generated_paths?.tailored_cv);
  out.cover_letter_ready = Boolean(docs.cover_letter || docs.tailored_cover_letter || docs.generated_paths?.cover_letter);
  return out;
}

function statusLabel(value) {
  const labels = {
    READY_TO_APPLY: "Ready to Apply",
    NEEDS_VERIFICATION: "Needs Verification",
    NOT_ELIGIBLE: "Not Eligible",
    prepared: "Prepared",
    review: "Ready to Review",
    opened: "Opened",
    submitted: "Submitted",
    applied: "Submitted",
    interviewing: "Interview",
    rejected: "Rejected",
    withdrawn: "Withdrawn",
    archived: "Archived",
    not_eligible: "Not Eligible",
    recommended: "Ready to Apply",
    needs_verification: "Needs Verification",
  };
  return labels[value] || value || "Needs Review";
}

function isClosedOrExpired(job) {
  const status = job.current_status || job.status || "";
  if (["CLOSED", "EXPIRED", "closed", "expired", "archived", "rejected", "withdrawn"].includes(status)) return true;
  if (!job.closing_date) return false;
  return String(job.closing_date).slice(0, 10) < new Date().toISOString().slice(0, 10);
}

function isClosingSoon(job) {
  if (!job.closing_date || isClosedOrExpired(job)) return false;
  const today = new Date(new Date().toISOString().slice(0, 10));
  const deadline = new Date(String(job.closing_date).slice(0, 10));
  const days = Math.ceil((deadline - today) / 86400000);
  return days >= 0 && days <= 7;
}

function parseMaybeJSON(value) {
  if (!value) return null;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch (_) {
    return null;
  }
}

function getPath(obj, path) {
  return path.split(".").reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), obj);
}

function mergeDefaults(base, updates) {
  for (const [key, value] of Object.entries(updates || {})) {
    if (value && typeof value === "object" && !Array.isArray(value) && base[key] && typeof base[key] === "object" && !Array.isArray(base[key])) {
      mergeDefaults(base[key], value);
    } else {
      base[key] = value;
    }
  }
  if (!Array.isArray(base.medical_education) || base.medical_education.length === 0) {
    base.medical_education = [{ degree: "MD", institution: "", graduation_year: "", verified: true }];
  }
  return base;
}

function defaultMedicalProfile() {
  return {
    personal: {
      first_name: "",
      last_name: "",
      email: "",
      phone: "",
      location: "Kabul, Afghanistan",
      nationality: "Afghan",
      gender: "",
      linkedin: "",
    },
    resume_path: "./cv.pdf",
    medical_education: [{ degree: "MD", institution: "", graduation_year: "", verified: true }],
    license_registration: { authority: "Ministry of Public Health", number: "", status: "Needs verification", verified: false },
    clinical_experience: { years: 0, settings: [] },
    work_history: [],
    skills: { medical: ["Clinical care", "Primary health care"], public_health: [], management: [] },
    languages: [
      { name: "Dari", level: "" },
      { name: "Pashto", level: "" },
      { name: "English", level: "" },
    ],
    certificates: [],
    ngo_humanitarian_experience: { years: 0, organizations: [] },
    preferences: {
      roles: ["Medical Officer", "Medical Doctor", "Physician", "Health Officer", "Nutrition Officer"],
      locations: ["Afghanistan", "Kabul"],
      preferred_locations: ["Kabul"],
      willing_to_relocate: false,
      field_deployment: false,
      remote_only: false,
    },
    job_sources: {
      acbar: { enabled: true, urls: ["https://www.acbar.org/jobs"] },
      reliefweb: { enabled: true, limit: 25 },
      official_career_pages: [],
      ats: { greenhouse: [], lever: [] },
    },
    search: { generic_job_boards_enabled: false, queries: ["Medical Officer Afghanistan", "Medical Doctor Afghanistan"], locations: ["Afghanistan", "Kabul"] },
    schedule: { enabled: true, job_watch_interval_hours: 6, discover_interval_hours: 6, score_interval_minutes: 60, deadline_alert_days: [7, 3, 1] },
    watcher: { enabled: true, scan_interval_hours: 6, deadline_alert_days: [7, 3, 1], auto_prepare_ready_to_apply: false, application_out_dir: "documents/applications" },
    notifications: { new_jobs: true, needs_verification: true, deadline_alerts: true, updates: true, closed: true, source_failures: true },
    ai: { enabled: false, enable_document_refinement: false },
  };
}
