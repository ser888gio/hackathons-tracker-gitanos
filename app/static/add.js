const form = document.querySelector("#projectForm");
const submitButton = document.querySelector("#submitProject");
const statusBox = document.querySelector("#addStatus");
const createdProject = document.querySelector("#createdProject");
const template = document.querySelector("#projectTemplate");

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

function techStackFromInput(value) {
  return value
    .split(/[\n,]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function payloadFromForm() {
  const data = new FormData(form);
  return {
    project_name: String(data.get("project_name") || "").trim(),
    hackathon_name: String(data.get("hackathon_name") || "").trim(),
    description: String(data.get("description") || "").trim(),
    category: String(data.get("category") || "other").trim(),
    tech_stack: techStackFromInput(String(data.get("tech_stack") || "")),
    project_url: String(data.get("project_url") || "").trim() || null,
    github_url: String(data.get("github_url") || "").trim() || null,
  };
}

function renderProject(project) {
  const node = template.content.cloneNode(true);
  node.querySelector(".category").textContent = project.hackathon_name
    ? `${project.hackathon_name} / ${project.category || "other"}`
    : project.category || "other";
  node.querySelector("h2").textContent = project.project_name;
  node.querySelector(".score").textContent = project.evaluation ? `${project.evaluation.rating}/10` : "-";
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
  createdProject.replaceChildren(node);
}

async function errorMessage(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return body.detail[0].msg;
  } catch {
    // fall through
  }
  return `Request failed with ${response.status}`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = payloadFromForm();
  if (!payload.project_name || !payload.hackathon_name || !payload.description) {
    setStatus("Project name, hackathon name, and description are required.", "error");
    return;
  }

  submitButton.disabled = true;
  createdProject.replaceChildren();
  setStatus("Adding project and running rating pipeline...", "info");

  try {
    const response = await fetch("/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response));
    }
    const project = await response.json();
    renderProject(project);
    form.reset();
    setStatus(`Added and rated ${project.project_name}.`, "info");
  } catch (error) {
    setStatus(`Could not add project: ${error.message}`, "error");
  } finally {
    submitButton.disabled = false;
  }
});
