from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import nodriver as uc
from nodriver import Browser, Config, cdp

from app.category import normalize_category
from app.config import settings

logger = logging.getLogger(__name__)
StatusCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]

CHROMIUM_DOCKER_FLAGS = [
    "--no-sandbox",
    "--headless=new",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-setuid-sandbox",
    "--single-process",
]


@dataclass(slots=True)
class ScrapedProject:
    project_name: str
    description: str
    category: str
    tech_stack: list[str]
    github_url: str | None = None
    demo_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "description": self.description,
            "category": self.category,
            "tech_stack": self.tech_stack,
            "github_url": self.github_url,
            "demo_url": self.demo_url,
        }


def page_url(base_url: str, page_number: int) -> str:
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunparse(parsed._replace(query=urlencode(query)))


def chromium_config() -> Config:
    config = Config(
        headless=settings.chromium_headless,
        sandbox=False,
        browser_executable_path=settings.chromium_path,
        browser_args=CHROMIUM_DOCKER_FLAGS,
    )
    return config


async def _wait_for_dom(page: Any) -> None:
    try:
        await page.find("//body", timeout=20)
    except Exception:
        logger.debug("page.find('//body') did not resolve before CDP readiness check", exc_info=True)

    for _ in range(40):
        ready_state = await _evaluate(page, "document.readyState")
        if ready_state in {"interactive", "complete"}:
            return
        await asyncio.sleep(0.25)


async def _evaluate(page: Any, expression: str) -> Any:
    result, exception_details = await page.send(
        cdp.runtime.evaluate(
            expression=expression,
            return_by_value=True,
            await_promise=True,
        )
    )
    if exception_details:
        raise RuntimeError(f"CDP evaluation failed: {exception_details}")
    return getattr(result, "value", None)


async def _extract_cards(page: Any) -> list[dict[str, Any]]:
    expression = r"""
(() => {
  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const absUrl = (href) => {
    try { return href ? new URL(href, location.href).href : null; }
    catch { return null; }
  };
  const tagTexts = (root) => Array.from(root.querySelectorAll(
    ".software-entry-labels a, .software-entry-labels span, .tag-list a, .tag-list span, .label, .tag"
  )).map((node) => clean(node.textContent)).filter(Boolean);

  const cardNodes = Array.from(document.querySelectorAll(
    ".software-entry, [data-software-id], article, li"
  ));

  const cards = cardNodes.map((card) => {
    const link = card.querySelector(
      ".software-entry-name a, h2 a, h3 a, h4 a, h5 a, a[href*='/software/']"
    );
    const href = absUrl(link && link.getAttribute("href"));
    if (!href || !href.includes("/software/")) return null;

    const name = clean((link && link.textContent) || "");
    const descriptionNode = card.querySelector(
      ".software-entry-description, .description, p"
    );
    const description = clean(descriptionNode && descriptionNode.textContent);
    return {
      project_name: name,
      description,
      tags: tagTexts(card),
      detail_url: href
    };
  }).filter((card) => card && card.project_name);

  const seen = new Set();
  return cards.filter((card) => {
    const key = `${card.project_name}|${card.detail_url}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
})()
"""
    value = await _evaluate(page, expression)
    return value if isinstance(value, list) else []


async def _extract_detail_project(page: Any) -> dict[str, Any]:
    expression = r"""
(() => {
  const clean = (value) => (value || "").replace(/\s+/g, " ").trim();
  const meta = (selector) => clean(document.querySelector(selector)?.getAttribute("content"));
  const absUrl = (href) => {
    try { return href ? new URL(href, location.href).href : null; }
    catch { return null; }
  };

  const title = clean(document.querySelector("#app-title")?.innerText) ||
    meta("meta[property='og:title']") ||
    meta("meta[itemprop='name']") ||
    clean(document.title.replace(/\s*\|\s*Devpost\s*$/i, ""));

  const tagline = clean(document.querySelector("#software-header p.large")?.innerText) ||
    meta("meta[property='og:description']") ||
    meta("meta[name='description']");

  const left = document.querySelector("#app-details-left");
  const storyBlocks = [];
  if (left) {
    for (const child of Array.from(left.children)) {
      if (child.id === "gallery" || child.id === "built-with") continue;
      if (child.matches("nav, .app-links, script, style")) continue;
      if (!child.querySelector("h1, h2, h3, p, li")) continue;
      const text = clean(child.innerText);
      if (text.length >= 80) storyBlocks.push(text);
    }
  }

  const story = storyBlocks.join("\n\n");
  const description = [tagline, story].filter(Boolean).join("\n\n");

  const techStack = Array.from(document.querySelectorAll("#built-with .cp-tag"))
    .map((node) => clean(node.textContent))
    .filter(Boolean);

  const appLinks = Array.from(document.querySelectorAll("[data-role='software-urls'] a, nav.app-links a"))
    .map((anchor) => absUrl(anchor.getAttribute("href")))
    .filter(Boolean);

  const githubUrl = appLinks.find((url) => /github\.com/i.test(url)) || null;
  const demoUrl = appLinks.find((url) => !/github\.com/i.test(url)) || null;

  return {
    project_name: title,
    description,
    tech_stack: [...new Set(techStack)],
    github_url: githubUrl,
    demo_url: demoUrl,
    url: location.href
  };
})()
"""
    value = await _evaluate(page, expression)
    return value if isinstance(value, dict) else {}


async def _navigate(browser: Browser, url: str) -> Any:
    page = await browser.get(url)
    await _wait_for_dom(page)
    return page


def _project_from_card(card: dict[str, Any], detail_project: dict[str, Any]) -> ScrapedProject | None:
    name = str(detail_project.get("project_name") or card.get("project_name") or "").strip()
    fallback_description = str(card.get("description") or "").strip()
    detail_description = str(detail_project.get("description") or "").strip()
    description = detail_description or fallback_description
    tags = card.get("tags") if isinstance(card.get("tags"), list) else []
    tech_stack = _string_tags(detail_project.get("tech_stack") or [])
    category_hints = [*_string_tags(tags), *tech_stack]
    if not name or not description:
        return None
    return ScrapedProject(
        project_name=name,
        description=description,
        category=normalize_category(category_hints, description),
        tech_stack=tech_stack,
        github_url=_optional_string(detail_project.get("github_url")),
        demo_url=_optional_string(detail_project.get("demo_url")),
    )


def _string_tags(tags: Iterable[Any]) -> list[str]:
    return [str(tag).strip() for tag in tags if str(tag).strip()]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def scrape_devpost_projects(
    start_url: str | None = None,
    max_projects: int | None = None,
    delay_seconds: float | None = None,
    status_callback: StatusCallback | None = None,
) -> list[dict[str, Any]]:
    """Scrape winning Devpost projects with nodriver and return plain dictionaries."""
    start_url = start_url or settings.devpost_search_url
    max_projects = settings.max_projects if max_projects is None else max_projects
    delay_seconds = settings.scraper_delay_seconds if delay_seconds is None else delay_seconds
    browser: Browser | None = None
    projects: list[ScrapedProject] = []

    try:
        await _publish(
            status_callback,
            "running",
            {
                "stage": "scraping",
                "message": "Starting Chromium for Devpost scraping.",
                "scraped": 0,
                "max_projects": max_projects,
                "current_url": start_url,
            },
        )
        browser = await uc.start(config=chromium_config())
        page_number = 1
        while True:
            if max_projects and len(projects) >= max_projects:
                await _publish(
                    status_callback,
                    "running",
                    {
                        "stage": "scraping",
                        "message": f"Reached MAX_PROJECTS limit ({max_projects}).",
                        "page": page_number,
                        "scraped": len(projects),
                        "max_projects": max_projects,
                        "current_url": page_url(start_url, page_number),
                    },
                )
                break

            results_url = page_url(start_url, page_number)
            await _publish(
                status_callback,
                "running",
                {
                    "stage": "scraping",
                    "message": f"Opening Devpost results page {page_number}.",
                    "page": page_number,
                    "scraped": len(projects),
                    "max_projects": max_projects,
                    "current_url": results_url,
                },
            )
            page = await _navigate(browser, results_url)
            cards = await _extract_cards(page)
            if not cards:
                await _publish(
                    status_callback,
                    "running",
                    {
                        "stage": "scraping",
                        "message": f"No project cards found on page {page_number}; stopping scraper.",
                        "page": page_number,
                        "scraped": len(projects),
                        "max_projects": max_projects,
                        "current_url": results_url,
                    },
                )
                break
            await _publish(
                status_callback,
                "running",
                {
                    "stage": "scraping",
                    "message": f"Found {len(cards)} project cards on page {page_number}.",
                    "page": page_number,
                    "cards_on_page": len(cards),
                    "scraped": len(projects),
                    "max_projects": max_projects,
                    "current_url": results_url,
                },
            )

            for card_index, card in enumerate(cards, start=1):
                if max_projects and len(projects) >= max_projects:
                    break

                detail_url = card.get("detail_url")
                detail_project: dict[str, Any] = {}
                if isinstance(detail_url, str) and detail_url:
                    project_name = str(card.get("project_name") or "project").strip()
                    await _publish(
                        status_callback,
                        "running",
                        {
                            "stage": "scraping",
                            "message": f"Reading detail page for {project_name}.",
                            "page": page_number,
                            "card": card_index,
                            "cards_on_page": len(cards),
                            "project_name": project_name,
                            "scraped": len(projects),
                            "max_projects": max_projects,
                            "current_url": detail_url,
                        },
                    )
                    detail_page = await _navigate(browser, detail_url)
                    detail_project = await _extract_detail_project(detail_page)
                    await asyncio.sleep(delay_seconds)
                    await _navigate(browser, results_url)

                project = _project_from_card(card, detail_project)
                if project:
                    projects.append(project)
                    await _publish(
                        status_callback,
                        "running",
                        {
                            "stage": "scraping",
                            "message": f"Scraped {project.project_name}.",
                            "page": page_number,
                            "card": card_index,
                            "cards_on_page": len(cards),
                            "project_name": project.project_name,
                            "scraped": len(projects),
                            "max_projects": max_projects,
                            "current_url": detail_url if isinstance(detail_url, str) else results_url,
                        },
                    )

            page_number += 1
            await asyncio.sleep(delay_seconds)
    finally:
        if browser is not None:
            browser.stop()

    return [project.to_dict() for project in projects]


async def _publish(
    status_callback: StatusCallback | None,
    state: str,
    payload: dict[str, Any],
) -> None:
    if status_callback is None:
        return
    result = status_callback(state, payload)
    if result is not None:
        await result
