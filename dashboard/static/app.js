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
    recommended: [],
    applications: [],
    stats: {},
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
        const res = await fetch("/api/jobs?limit=200&sort_by=discovered_at&sort_order=desc");
        const data = await res.json();
        this.jobs = (data.jobs || []).map(normalizeJob);
      } catch (_) {}
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
      const match = job.match || parseMaybeJSON(job.match_json) || {};
      return match.requirement_matches || [];
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
  out.metadata = parseMaybeJSON(out.metadata) || {};
  out.match = parseMaybeJSON(out.match_json) || null;
  if (!out.priority && out.match) out.priority = out.match.priority;
  return out;
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
    schedule: { enabled: true, discover_interval_hours: 12, score_interval_minutes: 60 },
    ai: { enabled: false, enable_document_refinement: false },
  };
}
