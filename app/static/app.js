const state = {
  projects: [],
  category: "",
  minRating: 0,
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
const categoryFilter = document.querySelector("#categoryFilter");
const ratingFilter = document.querySelector("#ratingFilter");
const ratingValue = document.querySelector("#ratingValue");
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

function filteredProjects() {
  return state.projects.filter((project) => {
    const categoryMatch = !state.category || project.category === state.category;
    const ratingMatch = ratingOf(project) >= state.minRating;
    return categoryMatch && ratingMatch;
  });
}

function render() {
  const projects = filteredProjects();
  grid.replaceChildren();
  ratingValue.textContent = `${state.minRating}+`;
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

categoryFilter.addEventListener("change", () => {
  state.category = categoryFilter.value;
  render();
});

ratingFilter.addEventListener("input", () => {
  state.minRating = Number(ratingFilter.value);
  render();
});

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
