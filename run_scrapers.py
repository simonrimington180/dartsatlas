import datetime
import subprocess
import smtplib
from email.message import EmailMessage
import os

# calculate yesterday's date
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

# paths to the eleven scraper scripts (adjust if your folder is different)
folder = r"C:\\darts_scrapers"
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

