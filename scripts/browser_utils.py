#!/usr/bin/env python3
"""Shared Playwright browser utilities used by all search/apply scripts."""

import os
import time
import random

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Playwright


HEADLESS = os.environ.get("BROWSER_HEADLESS", "true").lower() != "false"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def create_browser() -> tuple[Playwright, Browser, BrowserContext]:
    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return p, browser, context


def human_delay(min_s: float = 1.0, max_s: float = 3.0):
    time.sleep(random.uniform(min_s, max_s))


def safe_fill(page: Page, selector: str, value: str, timeout: int = 5000):
    """Fill a field if it exists; silently skip if not found."""
    try:
        el = page.wait_for_selector(selector, timeout=timeout)
        if el:
            el.fill(value)
    except Exception:
        pass


def safe_click(page: Page, selector: str, timeout: int = 5000) -> bool:
    """Click an element if it exists; return True on success."""
    try:
        el = page.wait_for_selector(selector, timeout=timeout)
        if el:
            el.click()
            return True
    except Exception:
        pass
    return False


def upload_file(page: Page, selector: str, file_path: str, timeout: int = 5000):
    """Set a file input to the given path."""
    try:
        el = page.wait_for_selector(selector, timeout=timeout)
        if el:
            el.set_input_files(file_path)
    except Exception:
        pass
