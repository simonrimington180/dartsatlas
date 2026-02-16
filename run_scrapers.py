import datetime
import subprocess
import smtplib
from email.message import EmailMessage
import os
import re
import sys
import time

# calculate yesterday's date
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

# use the folder this script is in (works on GitHub Actions + Windows)
folder = os.path.dirname(os.path.abspath(__file__))

# ----- AUTO PATCH: make all region scrapers wait longer + dump debug on failure -----
def patch_scraper_file(path: str) -> None:
    txt = open(path, "r", encoding="utf-8").read()

    # 1) replace wait_for_listing_render with a robust version + debug dumps
    wait_pat = re.compile(r"(?ms)^def wait_for_listing_render\(.*?\n(?=^\S|\Z)")
    new_wait = """def wait_for_listing_render(driver: webdriver.Chrome, timeout: int = 120) -> None:
    # Always wait for body first
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/tournaments/']"))
        )
        return
    except Exception:
        # dump debug so we can see what GitHub is actually loading
        try:
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source or "")
        except Exception:
            pass
        try:
            driver.save_screenshot("debug_page.png")
        except Exception:
            pass
        try:
            body_txt = driver.find_element(By.TAG_NAME, "body").text
            print("[DEBUG body text snippet]", body_txt[:800], flush=True)
        except Exception:
            pass
        raise
"""
    if "def wait_for_listing_render" in txt:
        txt = wait_pat.sub(new_wait + "\n", txt, count=1)

    # 2) ensure any calls that pass timeout=40 become timeout=120
    txt = txt.replace("wait_for_listing_render(driver, timeout=40)", "wait_for_listing_render(driver, timeout=120)")

    open(path, "w", encoding="utf-8").write(txt)

# Patch all region scripts in this folder (does not touch run_scrapers.py itself)
for fname in os.listdir(folder):
    if fname.endswith(".py") and fname not in ("run_scrapers.py",):
        patch_scraper_file(os.path.join(folder, fname))

# ----- RUN SCRIPTS -----
scripts = [
    os.path.join(folder, "yorkshire.py"),
    os.path.join(folder, "northwest.py"),
    os.path.join(folder, "southeast.py"),
    os.path.join(folder, "northeast.py"),
    os.path.join(folder, "midlands.py"),
    os.path.join(folder, "scotland.py"),
    os.path.join(folder, "ireland.py"),
    os.path.join(folder, "northernireland.py"),
    os.path.join(folder, "wales.py"),
    os.path.join(folder, "eastofengland.py"),
    os.path.join(folder, "southwest.py"),
]

for script in scripts:
    subprocess.run(["python", script, yesterday], check=True)

# build the filenames that will have been generated
file_names = [
    "southeast.txt",
    "northwest.txt",
    "yorkshire.txt",
    "northeast.txt",
    "midlands.txt",
    "scotland.txt",
    "ireland.txt",
    "northernireland.txt",
    "wales.txt",
    "eastofengland.txt",
    "southwest.txt",
]

file_paths = [os.path.join(folder, name) for name in file_names]

# compose email
msg = EmailMessage()
msg["Subject"] = f"Darts high-average results for {yesterday}"
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

msg.set_content(f"Attached are the high-average results for {yesterday}.")

# attach files if they exist (skip missing ones so email still sends)
for path in file_paths:
    if not os.path.exists(path):
        continue
    with open(path, "rb") as f:
        data = f.read()
    msg.add_attachment(
        data,
        maintype="text",
        subtype="plain",
        filename=os.path.basename(path),
    )

# send email via SMTP
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
    smtp.login("simonrimington@gmail.com", os.environ["GMAIL_APP_PASSWORD"])
    smtp.send_message(msg, to_addrs=recipients)
