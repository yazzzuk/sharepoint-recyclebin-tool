# SharePoint Recycle Bin Helper (Graph-only, Interactive) - Mirage cyber range helper
## Some help from a popular LLM - although it kept using the wrong endpoint. LLMs, eh.

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
```

## Fetch Microsoft Graph access token
`GRAPH_TOKEN="$(az account get-access-token --resource-type ms-graph --query accessToken -o tsv)"`

## Option A: paste token when prompted
`python sp_rb_interactive.py`

## Option B: pass token via flag
`python sp_rb_interactive.py --graph-token "$GRAPH_TOKEN"`

## Option C: use environment variable
`GRAPH_TOKEN="$GRAPH_TOKEN" python sp_rb_interactive.py`
