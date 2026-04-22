const state = {
  projects: [],
  category: "",
  minRating: 0,
};

const grid = document.querySelector("#projectGrid");
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
    statusBox.textContent = "";
    return;
  }
  statusBox.hidden = false;
  statusBox.textContent = message;
  statusBox.dataset.tone = tone;
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
    node.querySelector(".category").textContent = project.category || "other";
    node.querySelector("h2").textContent = project.project_name;
    node.querySelector(".score").textContent = project.evaluation ? `${project.evaluation.rating}/10` : "-";
    node.querySelector(".description").textContent = project.description || "";
    node.querySelector(".pros").textContent = project.evaluation?.feedback_pros || "Pending evaluation.";
    node.querySelector(".improvements").textContent = project.evaluation?.feedback_improvements || "Pending evaluation.";
    grid.append(node);
  }
}

async function loadProjects() {
  refreshButton.disabled = true;
  try {
    const response = await fetch("/projects");
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    state.projects = await response.json();
    setStatus("");
    render();
  } catch (error) {
    setStatus(`Could not load projects: ${error.message}`, "error");
  } finally {
    refreshButton.disabled = false;
  }
}

async function triggerPipeline() {
  pipelineButton.disabled = true;
  try {
    const response = await fetch("/trigger-pipeline", { method: "POST" });
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    const body = await response.json();
    setStatus(`Pipeline started: ${body.job_id}`, "info");
  } catch (error) {
    setStatus(`Could not start pipeline: ${error.message}`, "error");
  } finally {
    pipelineButton.disabled = false;
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

loadProjects();
