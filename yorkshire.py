#!/usr/bin/env python3
"""
Darts Atlas – Yesterday-only 85+ averages (Vault 16.0)

OUTPUT YOU ASKED FOR:
- No match/group links.
- Report rows are: Average, Player, Tournament, Section
- Sorted by Average (desc).

BEHAVIOUR:
- Opens ONLY the season results page you provided.
- Reads dates ONLY from the rendered tournament cards on that page.
- Scrapes ONLY tournaments dated yesterday (Europe/London), skips today,
  and STOPS as soon as it reaches any card older than yesterday.
- Scrapes:
    - /results  (matches/knockouts listing)
    - /groups + every /group/* page (group match listings)
- Extracts PLAYER NAMES + 3-dart averages shown as "Avg" directly from those listings.
  (Does NOT click into /matches pages.)
"""

import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import List, Tuple, Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

SEASON_RESULTS_URL = "https://www.dartsatlas.com/seasons/8cc6TbdDhVDq/tournaments/results"
THRESHOLD = 85.0
REPORT_PATH = "yorkshire.txt"

# Card date looks like: "2026 Feb 12"
DATE_RE = re.compile(r"\b(20\d{2})\s+([A-Za-z]{3})\s+(\d{1,2})\b")

# Only accept /tournaments/<id> where <id> is alphanumeric and not reserved
TOUR_PATH_RE = re.compile(r"^/tournaments/([A-Za-z0-9]+)$")
RESERVED_SLUGS = {"schedule", "results", "groups", "matches", "tournaments"}

# UPDATED: unicode/emoji friendly.
# Matches lines like:
# "Kelvin O’Keefe 3 Jack Brown 0 66.31 Avg 57.36 Avg"
# Works with:
# - straight ' and curly ’
# - emojis
# - accented letters
# - pretty much any unicode characters in names
PAIR_RE = re.compile(
    r"([^\r\n\d]+?)\s+\d+\s+([^\r\n\d]+?)\s+\d+\s+(\d+(?:\.\d+)?)\s*Avg\s+(\d+(?:\.\d+)?)\s*Avg",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class AvgRow:
    value: float
    player: str
    tournament: str
    section: str  # matches | groups

def london_today() -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/London")).date()
    except Exception:
        return datetime.now().date()

def parse_date(text: str) -> Optional[date]:
    txt = " ".join((text or "").split())
    m = DATE_RE.search(txt)
    if not m:
        return None
    y, mon, d = m.groups()
    try:
        month_num = datetime.strptime(mon, "%b").month
        return date(int(y), month_num, int(d))
    except Exception:
        return None

def start_driver() -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    return webdriver.Chrome(options=opts)

def wait_for_listing_render(driver: webdriver.Chrome, timeout: int = 90) -> None:
    # Wait for page body first
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    # Try to wait for tournaments
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/tournaments/']"))
        )
        return
    except Exception:
        pass

    # Fallback — sometimes page renders slower on GitHub
    import time
    time.sleep(10)

    # Try again
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/tournaments/']"))
    )
    def _has_date(drv: webdriver.Chrome) -> bool:
        try:
            body_text = drv.find_element(By.TAG_NAME, "body").text
            return bool(DATE_RE.search(" ".join(body_text.split())))
        except Exception:
            return False
    WebDriverWait(driver, timeout).until(lambda d: _has_date(d))

def href_to_path(href: str) -> str:
    if not href:
        return ""
    href = href.split("?", 1)[0].split("#", 1)[0]
    if href.startswith("http"):
        try:
            return "/" + href.split("://", 1)[1].split("/", 1)[1]
        except Exception:
            return ""
    return href if href.startswith("/") else "/" + href

def is_valid_tournament_path(path: str) -> bool:
    m = TOUR_PATH_RE.match(path or "")
    if not m:
        return False
    slug = m.group(1).lower()
    return slug not in RESERVED_SLUGS

def find_card_with_date(el) -> Optional[Tuple[str, date]]:
    cur = el
    for _ in range(25):
        try:
            cur = cur.find_element(By.XPATH, "..")
        except Exception:
            return None
        t = (cur.text or "").strip()
        if not t:
            continue
        d = parse_date(t)
        if d:
            return t, d
    return None

def collect_yesterday_tournaments(driver: webdriver.Chrome, today: date, yesterday: date) -> List[Tuple[str, str]]:
    print(f"[LOAD] {SEASON_RESULTS_URL}", flush=True)
    driver.get(SEASON_RESULTS_URL)
    wait_for_listing_render(driver, timeout=40)

    anchors = driver.find_elements(By.CSS_SELECTOR, "a[href^='/tournaments/']")
    results: List[Tuple[str, str]] = []
    seen = set()
    found_yesterday = False

    for a in anchors:
        href = a.get_attribute("href") or ""
        path = href_to_path(href)
        if not is_valid_tournament_path(path):
            continue

        card = find_card_with_date(a)
        if card is None:
            print("[STOP] Could not locate a date on a tournament card; stopping to avoid scanning other dates.", flush=True)
            break
        card_text, d = card

        if d == today:
            continue
        if d < yesterday:
            print(f"[STOP] Reached older date {d} (< {yesterday}).", flush=True)
            break
        if d == yesterday:
            found_yesterday = True
            url = "https://www.dartsatlas.com" + path
            if url in seen:
                continue
            seen.add(url)
            title = (a.text or "").strip()
            if not title:
                lines = [ln.strip() for ln in card_text.splitlines() if ln.strip()]
                lines = [ln for ln in lines if not DATE_RE.search(ln)]
                title = lines[0] if lines else url
            results.append((title, url))

    # If we never even reached yesterday, don't keep going.
    if not found_yesterday:
        print(f"[WARN] Did not encounter any {yesterday} cards on the season page.", flush=True)
    return results

def parse_player_avgs(text: str) -> List[Tuple[str, float]]:
    out: List[Tuple[str, float]] = []
    for m in PAIR_RE.finditer(text or ""):
        p1, p2, v1s, v2s = m.groups()
        try:
            v1 = float(v1s); v2 = float(v2s)
        except ValueError:
            continue
        out.append((p1.strip(), v1))
        out.append((p2.strip(), v2))
    return out

def scrape_text(driver: webdriver.Chrome, url: str) -> str:
    driver.get(url)
    WebDriverWait(driver, 40).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    return driver.find_element(By.TAG_NAME, "body").text

def scrape_tournament(driver: webdriver.Chrome, title: str, base_url: str) -> List[AvgRow]:
    rows: List[AvgRow] = []
    base = base_url.rstrip("/")

    # /results listing (do NOT click into /matches)
    text = scrape_text(driver, base + "/results")
    for player, avg in parse_player_avgs(text):
        if avg >= THRESHOLD:
            rows.append(AvgRow(avg, player, title, "matches"))

    # /groups listing then each group page
    driver.get(base + "/groups")
    WebDriverWait(driver, 40).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    group_links = []
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/group/']"):
        href = a.get_attribute("href")
        if href and "/group/" in href:
            group_links.append(href)
    group_links = list(dict.fromkeys(group_links))

    for gl in group_links:
        gt = scrape_text(driver, gl)
        for player, avg in parse_player_avgs(gt):
            if avg >= THRESHOLD:
                rows.append(AvgRow(avg, player, title, "groups"))

    return rows

def write_report(rows: List[AvgRow]) -> None:
    # Dedup and sort desc
    uniq = {(r.value, r.player, r.tournament, r.section): r for r in rows}.values()
    sorted_rows = sorted(uniq, key=lambda r: r.value, reverse=True)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("Value,Player,Tournament,Section\n")
        for r in sorted_rows:
            f.write(f"{r.value:.2f},{r.player},{r.tournament},{r.section}\n")

    print(f"[DONE] {len(sorted_rows)} rows -> {REPORT_PATH}", flush=True)

def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    today = london_today()
    yesterday = today - timedelta(days=1)
    print(f"Today (London): {today} | Scraping ONLY: {yesterday}", flush=True)

    driver = start_driver()
    try:
        tournaments = collect_yesterday_tournaments(driver, today=today, yesterday=yesterday)
        print(f"[FOUND] {len(tournaments)} tournaments dated {yesterday}", flush=True)
        if not tournaments:
            return

        all_rows: List[AvgRow] = []
        for title, url in tournaments:
            print(f"[SCRAPE] {title}", flush=True)
            rows = scrape_tournament(driver, title, url)
            print(f"        85+ rows found: {len(rows)}", flush=True)
            all_rows.extend(rows)

        write_report(all_rows)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
