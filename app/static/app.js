const state = {
  projects: [],
  search: "",
  category: "",
  hackathon: "",
  source: "",
  selectedTech: new Set(),
  minRating: 0,
  maxRating: 10,
  ratingPreset: "all",
  evaluationStatus: "all",
  requireGithub: false,
  requireDemo: false,
  sort: "newest",
  activeJobId: null,
  pollTimer: null,
  pollCount: 0,
  lastLoggedUrl: null,
};

const grid = document.querySelector("#projectGrid");
const statMaxProjects = document.querySelector("#statMaxProjects");
const statPages = document.querySelector("#statPages");
const statScraped = document.querySelector("#statScraped");
const statState = document.querySelector("#statState");

function updateScraperPanel(job) {
  if (job.max_projects !== undefined) statMaxProjects.textContent = job.max_projects;
  if (job.page !== undefined) statPages.textContent = job.page;
  if (job.scraped !== undefined) {
    statScraped.textContent = job.max_projects !== undefined
      ? `${job.scraped} / ${job.max_projects}`
      : job.scraped;
  }
  const state = job.status || "";
  statState.textContent = state || "—";
  statState.dataset.state = state;
}

const template = document.querySelector("#projectTemplate");
const statusBox = document.querySelector("#status");
const summary = document.querySelector("#summary");
const searchFilter = document.querySelector("#searchFilter");
const categoryFilter = document.querySelector("#categoryFilter");
const hackathonFilter = document.querySelector("#hackathonFilter");
const sourceFilter = document.querySelector("#sourceFilter");
const sortFilter = document.querySelector("#sortFilter");
const minRatingFilter = document.querySelector("#minRatingFilter");
const maxRatingFilter = document.querySelector("#maxRatingFilter");
const ratingPresetButtons = document.querySelectorAll("[data-rating-preset]");
const githubFilter = document.querySelector("#githubFilter");
const demoFilter = document.querySelector("#demoFilter");
const techStackFilter = document.querySelector("#techStackFilter");
const clearTechFilter = document.querySelector("#clearTechFilter");
const resetFilters = document.querySelector("#resetFilters");
const refreshButton = document.querySelector("#refreshButton");
const pipelineButton = document.querySelector("#pipelineButton");

function setStatus(message, tone = "info") {
  if (!message) {
    statusBox.hidden = true;
    statusBox.replaceChildren();
    return;
  }
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.dataset.tone = tone;
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderJobStatus(job) {
  updateScraperPanel(job);
  logScrapingUrl(job);
  statusBox.hidden = false;
  statusBox.dataset.tone = job.status === "failed" ? "error" : "info";
  statusBox.replaceChildren();

  const header = document.createElement("div");
  header.className = "status__header";

  const title = document.createElement("strong");
  title.textContent = `${job.status || "running"}${job.stage ? `: ${job.stage}` : ""}`;

  const meta = document.createElement("span");
  const parts = [];
  if (job.page) parts.push(`page ${job.page}`);
  if (job.scraped !== undefined && job.max_projects !== undefined) {
    parts.push(`scraped ${job.scraped}/${job.max_projects}`);
  } else if (job.scraped !== undefined) {
    parts.push(`scraped ${job.scraped}`);
  }
  if (job.total !== undefined) parts.push(`${job.evaluated || 0}/${job.total} evaluated`);
  if (job.skipped) parts.push(`${job.skipped} skipped`);
  if (job.max_projects !== undefined && job.scraped === undefined) parts.push(`max ${job.max_projects}`);
  if (state.pollCount > 0 && job.status !== "completed" && job.status !== "failed") {
    parts.push(`poll ${state.pollCount}`);
  }
  meta.textContent = parts.join(" | ");

  header.append(title, meta);
  statusBox.append(header);

  if (job.message) {
    const current = document.createElement("p");
    current.className = "status__current";
    current.textContent = job.message;
    statusBox.append(current);
  }

  if (job.current_url) {
    const url = document.createElement("a");
    url.className = "status__url";
    url.href = job.current_url;
    url.target = "_blank";
    url.rel = "noreferrer";
    url.textContent = job.current_url;
    statusBox.append(url);
  }

  const messages = (job.messages || []).slice(-6).reverse();
  if (messages.length > 0) {
    const list = document.createElement("ol");
    list.className = "status__log";
    for (const entry of messages) {
      const item = document.createElement("li");
      const time = formatTime(entry.at);
      item.textContent = time ? `${time} ${entry.message}` : entry.message;
      list.append(item);
    }
    statusBox.append(list);
  }
}

function logScrapingUrl(job) {
  if (!job.current_url || job.current_url === state.lastLoggedUrl) {
    return;
  }
  state.lastLoggedUrl = job.current_url;
  console.log(`[scraper] scraping URL: ${job.current_url}`);
}

function ratingOf(project) {
  return project.evaluation?.rating ?? 0;
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function clampRating(value, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(0, Math.min(10, Math.round(number)));
}

function projectSource(project) {
  const platform = String(project.hackathon_platform || "").trim();
  if (platform) return platform;
  const hackathonName = normalizeText(project.hackathon_name);
  return hackathonName.includes("manual") ? "Manual" : "Devpost";
}

function searchableText(project) {
  return normalizeText([
    project.project_name,
    project.hackathon_name,
    project.category,
    project.description,
    ...(project.tech_stack || []),
    project.evaluation?.feedback_pros,
    project.evaluation?.feedback_improvements,
  ].join(" "));
}

function matchesSearch(project) {
  const terms = normalizeText(state.search).split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const haystack = searchableText(project);
  return terms.every((term) => haystack.includes(term));
}

function matchesRating(project) {
  const hasEvaluation = Boolean(project.evaluation);
  if (state.evaluationStatus === "pending") {
    return !hasEvaluation;
  }
  if (state.evaluationStatus === "rated" && !hasEvaluation) {
    return false;
  }
  if (!hasEvaluation) {
    return state.minRating === 0 && state.maxRating === 10;
  }
  const rating = ratingOf(project);
  return rating >= state.minRating && rating <= state.maxRating;
}

function matchesTechStack(project) {
  if (state.selectedTech.size === 0) return true;
  const projectTags = new Set((project.tech_stack || []).map(normalizeText));
  for (const selectedTag of state.selectedTech) {
    if (!projectTags.has(selectedTag)) return false;
  }
  return true;
}

function compareProjectNames(left, right, field) {
  return String(left[field] || "").localeCompare(String(right[field] || ""), undefined, {
    sensitivity: "base",
  });
}

function sortedProjects(projects) {
  return [...projects].sort((left, right) => {
    if (state.sort === "rating-desc") {
      return ratingOf(right) - ratingOf(left) || compareProjectNames(left, right, "project_name");
    }
    if (state.sort === "rating-asc") {
      const leftRating = left.evaluation ? ratingOf(left) : 11;
      const rightRating = right.evaluation ? ratingOf(right) : 11;
      return leftRating - rightRating || compareProjectNames(left, right, "project_name");
    }
    if (state.sort === "project-asc") {
      return compareProjectNames(left, right, "project_name");
    }
    if (state.sort === "hackathon-asc") {
      return compareProjectNames(left, right, "hackathon_name") || compareProjectNames(left, right, "project_name");
    }
    return Date.parse(right.scraped_at || 0) - Date.parse(left.scraped_at || 0)
      || compareProjectNames(left, right, "project_name");
  });
}

function filteredProjects() {
  const projects = state.projects.filter((project) => {
    const searchMatch = matchesSearch(project);
    const categoryMatch = !state.category || project.category === state.category;
    const hackathonMatch = !state.hackathon || project.hackathon_name === state.hackathon;
    const sourceMatch = !state.source || normalizeText(projectSource(project)) === normalizeText(state.source);
    const githubMatch = !state.requireGithub || Boolean(project.github_url);
    const demoMatch = !state.requireDemo || Boolean(project.demo_url);
    return searchMatch
      && categoryMatch
      && hackathonMatch
      && sourceMatch
      && githubMatch
      && demoMatch
      && matchesRating(project)
      && matchesTechStack(project);
  });
  return sortedProjects(projects);
}

function setRatingPreset(preset) {
  if (preset === "pending") {
    state.minRating = 0;
    state.maxRating = 10;
    state.evaluationStatus = "pending";
  } else {
    state.minRating = preset === "8" ? 8 : preset === "6" ? 6 : 0;
    state.maxRating = 10;
    state.evaluationStatus = "all";
  }
  state.ratingPreset = preset;
  syncFilterControls();
  render();
}

function deriveRatingPreset() {
  if (state.evaluationStatus === "pending") return "pending";
  if (state.minRating === 8 && state.maxRating === 10) return "8";
  if (state.minRating === 6 && state.maxRating === 10) return "6";
  if (state.minRating === 0 && state.maxRating === 10) return "all";
  return "";
}

function syncFilterControls() {
  searchFilter.value = state.search;
  categoryFilter.value = state.category;
  hackathonFilter.value = state.hackathon;
  sourceFilter.value = state.source;
  sortFilter.value = state.sort;
  minRatingFilter.value = state.minRating;
  maxRatingFilter.value = state.maxRating;
  githubFilter.checked = state.requireGithub;
  demoFilter.checked = state.requireDemo;

  const activePreset = state.ratingPreset || deriveRatingPreset();
  for (const button of ratingPresetButtons) {
    button.classList.toggle("is-active", button.dataset.ratingPreset === activePreset);
  }
}

function updateRatingFromInputs(changedField) {
  const previousMin = state.minRating;
  const previousMax = state.maxRating;
  state.minRating = clampRating(minRatingFilter.value, previousMin);
  state.maxRating = clampRating(maxRatingFilter.value, previousMax);
  if (state.minRating > state.maxRating) {
    if (changedField === "min") {
      state.maxRating = state.minRating;
    } else {
      state.minRating = state.maxRating;
    }
  }
  state.evaluationStatus = "all";
  state.ratingPreset = deriveRatingPreset();
  syncFilterControls();
  render();
}

function resetAllFilters() {
  state.search = "";
  state.category = "";
  state.hackathon = "";
  state.source = "";
  state.selectedTech.clear();
  state.minRating = 0;
  state.maxRating = 10;
  state.ratingPreset = "all";
  state.evaluationStatus = "all";
  state.requireGithub = false;
  state.requireDemo = false;
  state.sort = "newest";
  renderFilterOptions();
  syncFilterControls();
  render();
}

function renderHackathonOptions() {
  const selected = state.hackathon;
  const hackathons = [...new Set(state.projects.map((project) => project.hackathon_name).filter(Boolean))]
    .sort((left, right) => left.localeCompare(right, undefined, { sensitivity: "base" }));
  if (selected && !hackathons.includes(selected)) {
    state.hackathon = "";
  }

  hackathonFilter.replaceChildren();
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "All hackathons";
  hackathonFilter.append(allOption);

  for (const hackathon of hackathons) {
    const option = document.createElement("option");
    option.value = hackathon;
    option.textContent = hackathon;
    hackathonFilter.append(option);
  }
  hackathonFilter.value = state.hackathon;
}

function renderTechStackOptions() {
  const counts = new Map();
  for (const project of state.projects) {
    const projectTags = new Set((project.tech_stack || []).map((tag) => String(tag || "").trim()).filter(Boolean));
    for (const tag of projectTags) {
      const key = normalizeText(tag);
      const current = counts.get(key) || { label: tag, count: 0 };
      current.count += 1;
      counts.set(key, current);
    }
  }

  for (const selectedTag of [...state.selectedTech]) {
    if (!counts.has(selectedTag)) {
      state.selectedTech.delete(selectedTag);
    }
  }

  const tags = [...counts.entries()].sort(([, left], [, right]) => {
    return right.count - left.count || left.label.localeCompare(right.label, undefined, { sensitivity: "base" });
  });

  techStackFilter.replaceChildren();
  if (tags.length === 0) {
    const empty = document.createElement("span");
    empty.className = "chip-group__empty";
    empty.textContent = "No stack tags yet";
    techStackFilter.append(empty);
    clearTechFilter.disabled = true;
    return;
  }

  for (const [key, tag] of tags) {
    const button = document.createElement("button");
    button.className = "chip";
    button.type = "button";
    button.dataset.tech = key;
    button.classList.toggle("is-active", state.selectedTech.has(key));
    button.setAttribute("aria-pressed", state.selectedTech.has(key) ? "true" : "false");
    button.title = `${tag.count} project${tag.count === 1 ? "" : "s"}`;

    const label = document.createElement("span");
    label.textContent = tag.label;
    const count = document.createElement("span");
    count.className = "chip__count";
    count.textContent = tag.count;
    button.append(label, count);
    techStackFilter.append(button);
  }
  clearTechFilter.disabled = state.selectedTech.size === 0;
}

function renderFilterOptions() {
  renderHackathonOptions();
  renderTechStackOptions();
  syncFilterControls();
}

function render() {
  const projects = filteredProjects();
  grid.replaceChildren();
  summary.textContent = `${projects.length} of ${state.projects.length} projects`;

  if (projects.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = state.projects.length === 0 ? "No projects yet." : "No projects match the current filters.";
    grid.append(empty);
    return;
  }

  for (const project of projects) {
    const node = template.content.cloneNode(true);
    node.querySelector(".category").textContent = project.hackathon_name
      ? `${project.hackathon_name} / ${project.category || "other"}`
      : project.category || "other";
    node.querySelector("h2").textContent = project.project_name;
    node.querySelector(".score").textContent = project.evaluation ? `${project.evaluation.rating}/10` : "-";
    node.querySelector(".delete-project").addEventListener("click", () => deleteProject(project));
    node.querySelector(".description").textContent = project.description || "";
    const stack = node.querySelector(".stack");
    for (const tag of project.tech_stack || []) {
      const item = document.createElement("span");
      item.textContent = tag;
      stack.append(item);
    }
    if ((project.tech_stack || []).length === 0) {
      stack.remove();
    }

    const links = node.querySelector(".project-links");
    if (project.github_url) {
      const github = document.createElement("a");
      github.href = project.github_url;
      github.target = "_blank";
      github.rel = "noreferrer";
      github.textContent = "GitHub";
      links.append(github);
    }
    if (project.demo_url) {
      const demo = document.createElement("a");
      demo.href = project.demo_url;
      demo.target = "_blank";
      demo.rel = "noreferrer";
      demo.textContent = "Project";
      links.append(demo);
    }
    if (!project.github_url && !project.demo_url) {
      links.remove();
    }

    node.querySelector(".pros").textContent = project.evaluation?.feedback_pros || "Pending evaluation.";
    node.querySelector(".improvements").textContent = project.evaluation?.feedback_improvements || "Pending evaluation.";
    grid.append(node);
  }
}

async function loadProjects() {
  refreshButton.disabled = true;
  try {
    const response = await fetch("/projects", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    state.projects = await response.json();
    if (!state.activeJobId) {
      setStatus("");
    }
    renderFilterOptions();
    render();
  } catch (error) {
    setStatus(`Could not load projects: ${error.message}`, "error");
  } finally {
    refreshButton.disabled = false;
  }
}

async function deleteProject(project) {
  const confirmed = window.confirm(`Delete "${project.project_name}" from the visible project list?`);
  if (!confirmed) return;

  const previousProjects = state.projects;
  state.projects = state.projects.filter((item) => item.id !== project.id);
  renderFilterOptions();
  render();

  try {
    const response = await fetch(`/projects/${project.id}`, {
      method: "DELETE",
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    setStatus(`Deleted ${project.project_name}. It will be skipped if scraped again.`, "info");
  } catch (error) {
    state.projects = previousProjects;
    renderFilterOptions();
    render();
    setStatus(`Could not delete project: ${error.message}`, "error");
  }
}

async function triggerPipeline() {
  pipelineButton.disabled = true;
  try {
    const response = await fetch("/trigger-pipeline", { method: "POST", cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    const body = await response.json();
    state.activeJobId = body.job_id;
    renderJobStatus({
      job_id: body.job_id,
      status: "accepted",
      stage: "queued",
      scraped: body.scraped ?? 0,
      max_projects: body.max_projects,
      message: "Pipeline accepted. Starting status polling now.",
      messages: [{ at: new Date().toISOString(), message: "Pipeline accepted. Starting status polling now." }],
    });
    startPollingJob(body.job_id);
  } catch (error) {
    setStatus(`Could not start pipeline: ${error.message}`, "error");
  } finally {
    pipelineButton.disabled = false;
  }
}

async function pollJob(jobId) {
  try {
    state.pollCount += 1;
    const response = await fetch(`/jobs/${jobId}`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    const job = await response.json();
    renderJobStatus(job);
    if (job.status === "completed") {
      stopPollingJob();
      await loadProjects();
      renderJobStatus(job);
      state.activeJobId = null;
    }
    if (job.status === "failed") {
      stopPollingJob();
      state.activeJobId = null;
    }
  } catch (error) {
    setStatus(`Could not load pipeline status: ${error.message}`, "error");
  }
}

function startPollingJob(jobId) {
  stopPollingJob();
  state.pollCount = 0;
  pollJob(jobId);
  state.pollTimer = window.setInterval(() => pollJob(jobId), 1500);
}

function stopPollingJob() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function resumeLatestJob() {
  try {
    const response = await fetch("/jobs/latest", { cache: "no-store" });
    if (response.status === 404) return;
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    const job = await response.json();
    renderJobStatus(job);
    if (job.status === "accepted" || job.status === "running") {
      state.activeJobId = job.job_id;
      startPollingJob(job.job_id);
    }
  } catch (error) {
    setStatus(`Could not load latest pipeline status: ${error.message}`, "error");
  }
}

searchFilter.addEventListener("input", () => {
  state.search = searchFilter.value;
  render();
});

categoryFilter.addEventListener("change", () => {
  state.category = categoryFilter.value;
  render();
});

hackathonFilter.addEventListener("change", () => {
  state.hackathon = hackathonFilter.value;
  render();
});

sourceFilter.addEventListener("change", () => {
  state.source = sourceFilter.value;
  render();
});

sortFilter.addEventListener("change", () => {
  state.sort = sortFilter.value;
  render();
});

minRatingFilter.addEventListener("input", () => updateRatingFromInputs("min"));
maxRatingFilter.addEventListener("input", () => updateRatingFromInputs("max"));

for (const button of ratingPresetButtons) {
  button.addEventListener("click", () => setRatingPreset(button.dataset.ratingPreset));
}

githubFilter.addEventListener("change", () => {
  state.requireGithub = githubFilter.checked;
  render();
});

demoFilter.addEventListener("change", () => {
  state.requireDemo = demoFilter.checked;
  render();
});

techStackFilter.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : event.target.parentElement;
  const button = target?.closest("[data-tech]");
  if (!button) return;
  const tag = button.dataset.tech;
  if (state.selectedTech.has(tag)) {
    state.selectedTech.delete(tag);
  } else {
    state.selectedTech.add(tag);
  }
  renderTechStackOptions();
  render();
});

clearTechFilter.addEventListener("click", () => {
  state.selectedTech.clear();
  renderTechStackOptions();
  render();
});

resetFilters.addEventListener("click", resetAllFilters);

refreshButton.addEventListener("click", loadProjects);
pipelineButton.addEventListener("click", triggerPipeline);

async function loadConfig() {
  try {
    const response = await fetch("/config", { cache: "no-store" });
    if (!response.ok) return;
    const cfg = await response.json();
    if (cfg.max_projects !== undefined) statMaxProjects.textContent = cfg.max_projects;
  } catch {
    // non-critical
  }
}

loadConfig();
loadProjects();
resumeLatestJob();
