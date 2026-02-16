import datetime
import os
import re
import smtplib
import subprocess
from email.message import EmailMessage
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


THRESHOLD = 85.0

# Card date looks like: "2026 Feb 15"
DATE_RE = re.compile(r"\b(20\d{2})\s+([A-Za-z]{3})\s+(\d{1,2})\b")

# Tournament path: /tournaments/<id>
TOUR_PATH_RE = re.compile(r"^/tournaments/([A-Za-z0-9]+)$")
RESERVED_SLUGS = {"schedule", "results", "groups", "matches", "tournaments"}

# Match lines contain “Best of X … <P1> <score> <P2> <score> <avg> Avg <avg> Avg”
BESTOF_PAIR_RE = re.compile(
    r"Best\s+of\s+\d+\s+(.+?)\s+\d+\s+(.+?)\s+\d+\s+(\d+(?:\.\d+)?)\s*Avg\s+(\d+(?:\.\d+)?)\s*Avg",
    re.IGNORECASE,
)

# For extracting constants from your existing region scripts
SEASON_URL_RE = re.compile(r'^\s*SEASON_RESULTS_URL\s*=\s*"([^"]+)"\s*$', re.M)
REPORT_PATH_RE = re.compile(r'^\s*REPORT_PATH\s*=\s*"([^"]+)"\s*$', re.M)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def london_today() -> datetime.date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Europe/London")).date()
    except Exception:
        return datetime.date.today()


def parse_date(text: str) -> Optional[datetime.date]:
    txt = " ".join((text or "").split())
    m = DATE_RE.search(txt)
    if not m:
        return None
    y, mon, d = m.groups()
    try:
        month_num = datetime.datetime.strptime(mon, "%b").month
        return datetime.date(int(y), month_num, int(d))
    except Exception:
        return None


def is_valid_tournament_path(path: str) -> bool:
    m = TOUR_PATH_RE.match(path or "")
    if not m:
        return False
    slug = m.group(1).lower()
    return slug not in RESERVED_SLUGS


def http_get(url: str) -> str:
    r = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"},
        timeout=60,
    )
    r.raise_for_status()
    return r.text


def collect_yesterday_tournaments(season_url: str, today: datetime.date, yesterday: datetime.date) -> List[Tuple[str, str]]:
    """
    Traverse the HTML in document order:
    - keep track of the most recent date string seen
    - when we see a tournament link, attach it to the current date
    - stop once we pass older than yesterday after having found yesterday
    """
    html = http_get(season_url)
    soup = BeautifulSoup(html, "html.parser")

    results: List[Tuple[str, str]] = []
    seen = set()
    current_date: Optional[datetime.date] = None
    found_yesterday = False

    body = soup.body or soup

    for node in body.descendants:
        # Update current_date whenever we see something that looks like "2026 Feb 15"
        if isinstance(node, NavigableString):
            d = parse_date(str(node))
            if d:
                current_date = d
                continue

        # Collect tournament links
        if isinstance(node, Tag) and node.name == "a":
            href = node.get("href") or ""
            if not href.startswith("/"):
                continue
            href = href.split("?", 1)[0].split("#", 1)[0]

            if not is_valid_tournament_path(href):
                continue

            if current_date is None:
                continue

            # Skip today
            if current_date == today:
                continue

            # Stop if we've already hit yesterday and now we're older
            if current_date < yesterday and found_yesterday:
                break

            if current_date == yesterday:
                found_yesterday = True
                full_url = "https://www.dartsatlas.com" + href
                if full_url in seen:
                    continue
                seen.add(full_url)
                title = " ".join(node.get_text(" ", strip=True).split())
                if not title:
                    title = full_url
                results.append((title, full_url))

    return results


def parse_player_avgs_from_html(html: str) -> List[Tuple[str, float]]:
    """
    Pulls match lines from the rendered page text; works for:
    - /results (knockouts/matches list)
    - /group/* (group match list)
    """
    soup = BeautifulSoup(html, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())

    out: List[Tuple[str, float]] = []
    for m in BESTOF_PAIR_RE.finditer(text):
        p1, p2, v1s, v2s = m.groups()
        try:
            v1 = float(v1s)
            v2 = float(v2s)
        except ValueError:
            continue
        out.append((p1.strip(), v1))
        out.append((p2.strip(), v2))
    return out


def scrape_tournament(title: str, base_url: str) -> List[Tuple[float, str, str, str]]:
    """
    Returns rows: (avg, player, tournament, section)
    section: matches | groups
    """
    rows: List[Tuple[float, str, str, str]] = []
    base = base_url.rstrip("/")

    # Matches/knockouts listing is at /results (as per your original scripts)
    matches_html = http_get(base + "/results")
    for player, avg in parse_player_avgs_from_html(matches_html):
        if avg >= THRESHOLD:
            rows.append((avg, player, title, "matches"))

    # Groups index
    groups_html = http_get(base + "/groups")
    groups_soup = BeautifulSoup(groups_html, "html.parser")

    group_links: List[str] = []
    for a in groups_soup.select("a[href*='/group/']"):
        href = a.get("href") or ""
        if "/group/" in href:
            if href.startswith("/"):
                href = "https://www.dartsatlas.com" + href
            group_links.append(href)

    # Dedup while preserving order
    seen = set()
    group_links = [u for u in group_links if not (u in seen or seen.add(u))]

    for gl in group_links:
        gl_html = http_get(gl)
        for player, avg in parse_player_avgs_from_html(gl_html):
            if avg >= THRESHOLD:
                rows.append((avg, player, title, "groups"))

    return rows


def write_report(report_path: str, rows: List[Tuple[float, str, str, str]]) -> None:
    # Dedup + sort desc
    uniq = {(a, p, t, s) for (a, p, t, s) in rows}
    sorted_rows = sorted(uniq, key=lambda r: r[0], reverse=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("Value,Player,Tournament,Section\n")
        for avg, player, tournament, section in sorted_rows:
            f.write(f"{avg:.2f},{player},{tournament},{section}\n")


def load_region_configs(folder: str) -> List[Tuple[str, str]]:
    """
    Reads your existing region scripts and extracts:
    - SEASON_RESULTS_URL
    - REPORT_PATH
    Returns list of (season_url, report_path)
    """
    configs: List[Tuple[str, str]] = []

    for fname in sorted(os.listdir(folder)):
        if not fname.endswith(".py"):
            continue
        if fname == "run_scrapers.py":
            continue

        path = os.path.join(folder, fname)
        txt = open(path, "r", encoding="utf-8").read()

        m1 = SEASON_URL_RE.search(txt)
        m2 = REPORT_PATH_RE.search(txt)
        if not m1 or not m2:
            # Skip files that aren't region scrapers
            continue

        season_url = m1.group(1).strip()
        report_path = m2.group(1).strip()
        # If report_path was relative in script, make it relative to repo folder
        if not os.path.isabs(report_path):
            report_path = os.path.join(folder, report_path)

        configs.append((season_url, report_path))

    return configs


def main() -> None:
    folder = os.path.dirname(os.path.abspath(__file__))

    today = london_today()
    yesterday = today - datetime.timedelta(days=1)
    print(f"Today (London): {today} | Scraping ONLY: {yesterday}", flush=True)

    configs = load_region_configs(folder)
    if not configs:
        raise RuntimeError("Could not find any region scripts with SEASON_RESULTS_URL and REPORT_PATH.")

    # Run all regions
    for season_url, report_path in configs:
        print(f"[LOAD] {season_url}", flush=True)

        tournaments = collect_yesterday_tournaments(season_url, today=today, yesterday=yesterday)
        print(f"[FOUND] {len(tournaments)} tournaments dated {yesterday}", flush=True)

        all_rows: List[Tuple[float, str, str, str]] = []
        for title, url in tournaments:
            print(f"[SCRAPE] {title}", flush=True)
            rows = scrape_tournament(title, url)
            print(f"        85+ rows found: {len(rows)}", flush=True)
            all_rows.extend(rows)

        # If no tournaments or no 85+ rows, you still get a file with just the header
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        write_report(report_path, all_rows)
        print(f"[DONE] -> {report_path}", flush=True)

    # Email results
    yesterday_str = yesterday.isoformat()

    msg = EmailMessage()
    msg["Subject"] = f"Darts high-average results for {yesterday_str}"
    msg["From"] = "simonrimington@gmail.com"

    recipients = [
        "simon.rimington@dartscircuit.com",
        "adam.mould@dartscircuit.com",
        "claire.louise@dartscircuit.com",
        "karl.coleman@dartscircuit.com",
        "matt.yarrow@dartscircuit.com",
        "hywel.llewellyn@dartscircuit.com",
        "andrew.fletcher@dartscircuit.com",
        "john.otoole@dartscircuit.com",
        "paul.hale@dartscircuit.com",
        "james.mulvaney@dartscircuit.com",
        "scott@dartscircuit.com",
    ]
    msg["To"] = ", ".join(recipients)
    msg.set_content(f"Attached are the high-average results for {yesterday_str}.")

    # Attach any report files that exist
    attached = 0
    for _, report_path in configs:
        if not os.path.exists(report_path):
            continue
        with open(report_path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="text",
                subtype="plain",
                filename=os.path.basename(report_path),
            )
            attached += 1

    print(f"[EMAIL] Attaching {attached} report files", flush=True)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login("simonrimington@gmail.com", os.environ["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg, to_addrs=recipients)

    print("[EMAIL] Sent", flush=True)


if __name__ == "__main__":
    main()
