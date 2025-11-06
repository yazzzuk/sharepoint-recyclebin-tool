# SharePoint Recycle Bin Helper (Graph-only, Interactive)

Interactive CLI tool to **list** and **restore** SharePoint files deleted from Microsoft Teams channels — using **only** a Microsoft Graph access token.

> ✅ Uses **Graph beta** batch restore endpoint:  
> `POST /beta/sites/{siteId}/recycleBin/items/restore` with `{"ids": ["..."]}`  
> ✅ No app registration, no refresh token, no SPO fallback.

---

## Features

- Just paste or pass your **Graph token**
- Pick **Team → Channel (context) → Site** automatically.
- List **Recycle Bin** items with original folder path.
- Restore a chosen file.
- **Poll** for the item to reappear and **download** it locally.

---

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
