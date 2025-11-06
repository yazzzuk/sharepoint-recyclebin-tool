#!/usr/bin/env python3
# sp_rb_interactive.py — Graph-only, interactive SharePoint Recycle Bin helper
#
# Flow:
#  - Token via --graph-token | env GRAPH_TOKEN | input()
#  - List Teams -> pick number
#  - List Channels (context) -> pick number
#  - Resolve Site (ID + URL)
#  - List recycle-bin items (with deletedFromLocation) -> pick number
#  - Restore via batch endpoint (POST /beta/sites/{siteId}/recycleBin/items/restore)
#  - Poll for reappearance, then download to current dir
#
# Requirements: pip install requests

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from typing import Optional, List

import requests

MSV1   = "https://graph.microsoft.com/v1.0"
MSBETA = "https://graph.microsoft.com/beta"

# ---------- HTTP helpers ----------
def gget(url, tok, params=None):
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.get(url, headers=h, params=params, timeout=30)
    if not r.ok:
        raise RuntimeError(f"[GET] {r.status_code} {url}\n{r.text}")
    return r.json()

def gpost_json(url, tok, body):
    # Accept 200/201/202/204/207; 207 is normal for batch restore
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    r = requests.post(url, headers=h, json=body, timeout=30)
    if r.status_code not in (200,201,202,204,207):
        raise RuntimeError(f"[POST] {r.status_code} {url}\n{r.text}")
    return r.json() if r.text else {}

def paginate(url, tok):
    while True:
        data = gget(url, tok)
        for row in data.get("value", []):
            yield row
        url = data.get("@odata.nextLink")
        if not url:
            break

# ---------- Utilities ----------
def prompt_choice(rows, render_fn, title="Choose an item"):
    """Simple number-or-quit selector (no filters, no 'all')."""
    if not rows:
        raise SystemExit("Nothing to choose from.")
    print(f"\n-- {title} --")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3}. {render_fn(r)}")
    while True:
        sel = input("Enter number (or q to quit): ").strip().lower()
        if sel in ("q", "quit", "exit"):
            raise SystemExit(0)
        if not sel.isdigit():
            print("Please enter a number from the list, or q to quit."); continue
        idx = int(sel)
        if 1 <= idx <= len(rows):
            return rows[idx-1]
        print("Out of range; try again.")

def safe_join_url_path(*parts):
    # Build a Graph drive/root:/path: segment with safe encoding
    segs = [urllib.parse.quote(p, safe=" @()&-_.") for p in parts if p]
    return "/".join(segs)

def site_from_team(team_id, tok):
    d = gget(f"{MSV1}/groups/{team_id}/sites/root", tok)
    sid  = d.get("id")
    surl = d.get("webUrl")
    if not sid or not surl:
        raise RuntimeError("Failed to resolve Site from Team.")
    return sid, surl

def list_teams(tok):
    return list(paginate(f"{MSV1}/me/joinedTeams", tok))

def list_channels(team_id, tok):
    url = f"{MSV1}/teams/{team_id}/channels?$select=id,displayName,membershipType"
    return list(paginate(url, tok))

def list_recyclebin(site_id, tok, top=200):
    items = []
    url = f"{MSBETA}/sites/{site_id}/recycleBin/items?$top={top}"
    for row in paginate(url, tok):
        db = row.get("deletedBy") or {}
        deleted_by = (db.get("user") or {}).get("displayName") or db.get("displayName")
        items.append({
            "id": row.get("id"),
            "name": row.get("name"),
            "size": row.get("size"),
            "deletedDateTime": row.get("deletedDateTime"),
            "deletedBy": deleted_by,
            "deletedFromLocation": row.get("deletedFromLocation"),
            "webUrl": row.get("webUrl"),
        })
    return items

def batch_restore(site_id, tok, ids: List[str]):
    url = f"{MSBETA}/sites/{site_id}/recycleBin/items/restore"
    body = {"ids": ids}
    return gpost_json(url, tok, body)

def derive_drive_rel_path(deleted_from_location: Optional[str]) -> Optional[str]:
    """
    Input:  'sites/DefaultDirectory/Shared Documents/Platform architecture/Processes'
    Output: 'Shared Documents/Platform architecture/Processes'
    """
    if not deleted_from_location:
        return None
    p = deleted_from_location.strip().lstrip("/")
    # Prefer the tail that starts once at 'Shared Documents'
    if "Shared Documents" in p:
        return p[p.rfind("Shared Documents"):]
    # Fallback: strip leading 'sites/<site>/' if present
    m2 = re.match(r"^sites/[^/]+/(.+)$", p)
    return m2.group(1) if m2 else p

def get_drive_item_by_exact_path(site_id, tok, drive_rel_path, name):
    """GET /sites/{siteId}/drive/root:/<drive_rel_path>/<name>"""
    if not drive_rel_path or not name:
        return None
    path = safe_join_url_path(drive_rel_path, name)
    url = f"{MSV1}/sites/{site_id}/drive/root:/{path}"
    try:
        return gget(url, tok)
    except Exception:
        return None

def list_children(site_id, tok, drive_rel_path):
    """GET children for /drive/root:/<drive_rel_path>:/children"""
    if not drive_rel_path:
        return []
    path = safe_join_url_path(drive_rel_path)
    url = f"{MSV1}/sites/{site_id}/drive/root:/{path}:/children"
    try:
        data = gget(url, tok)
        return data.get("value", [])
    except Exception:
        return []

def search_by_name(site_id, tok, name):
    """Search entire drive by filename"""
    q = urllib.parse.quote(name, safe="")
    url = f"{MSV1}/sites/{site_id}/drive/root/search(q='{q}')"
    try:
        return list(paginate(url, tok))
    except Exception:
        return []

def download_file(site_id, tok, drive_item, out_dir="."):
    """Download /sites/{siteId}/drive/items/{id}/content to local file"""
    item_id = drive_item.get("id")
    name    = drive_item.get("name") or f"download_{item_id}"
    url     = f"{MSV1}/sites/{site_id}/drive/items/{item_id}/content"
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.get(url, headers=h, timeout=120, stream=True)
    r.raise_for_status()
    local = os.path.join(out_dir, name)
    with open(local, "wb") as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return local

def wait_for_file(site_id, tok, drive_rel_path, name, attempts=6, sleep_sec=2):
    """
    Poll for the restored file to appear (eventual consistency).
    Strategy per attempt:
     1) exact path,
     2) list folder + pick newest candidate,
     3) whole-drive search (preferring expected parent path).
    """
    for _ in range(attempts):
        # 1) exact
        item = get_drive_item_by_exact_path(site_id, tok, drive_rel_path, name)
        if item:
            return item
        # 2) folder listing
        children = list_children(site_id, tok, drive_rel_path) if drive_rel_path else []
        if children:
            base = name.rsplit(".", 1)[0]
            cand = [c for c in children if isinstance(c.get("name"), str) and (c["name"] == name or c["name"].startswith(base))]
            cand.sort(key=lambda c: c.get("lastModifiedDateTime", ""), reverse=True)
            if cand:
                return cand[0]
        # 3) whole-drive search
        results = search_by_name(site_id, tok, name)
        if results:
            if drive_rel_path:
                pref = []
                enc = drive_rel_path.replace(" ", "%20")
                for r in results:
                    p = (r.get("parentReference") or {}).get("path") or ""
                    if enc in p or drive_rel_path in urllib.parse.unquote(p):
                        pref.append(r)
                results = pref or results
            results.sort(key=lambda r: r.get("lastModifiedDateTime", ""), reverse=True)
            return results[0]
        time.sleep(sleep_sec)
    return None

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(description="Interactive Graph-only SharePoint Recycle Bin helper.")
    ap.add_argument("--graph-token", help="Graph access token (or set env GRAPH_TOKEN).")
    ap.add_argument("--top", type=int, default=500, help="How many recycle bin items to retrieve (default 500).")
    args = ap.parse_args()

    token = args.graph_token or os.environ.get("GRAPH_TOKEN")
    if not token:
        print("=== SharePoint Recycle Bin helper (Graph-only, interactive) ===")
        print("Paste a Graph access token (e.g. from: az account get-access-token --resource-type ms-graph --query accessToken -o tsv)")
        token = input("Graph token: ").strip()
    if not token:
        print("No token provided."); sys.exit(1)

    # 1) Teams
    print("\nFetching your Teams...")
    teams = list_teams(token)
    team = prompt_choice(
        teams,
        lambda t: f"{t.get('displayName','(no name)')}  [{t.get('id')}]",
        title="Teams"
    )
    team_id = team["id"]
    print(f"\nSelected Team: {team.get('displayName')}")

    # 2) Channels (context)
    print("\nFetching channels (for context)...")
    chans = list_channels(team_id, token)
    if chans:
        chan = prompt_choice(
            chans,
            lambda c: f"{c.get('displayName')} ({c.get('membershipType')})  [{c.get('id')}]",
            title="Channels"
        )
        print(f"\nSelected Channel: {chan.get('displayName')}")
    else:
        print("No channels returned (continuing).")

    # 3) Site
    print("\nResolving SharePoint site for the Team...")
    site_id, site_url = site_from_team(team_id, token)
    print(f"Site: {site_url}\nSiteId: {site_id}")

    # 4) Recycle bin items
    print("\nFetching recycle bin items...")
    items = list_recyclebin(site_id, token, top=args.top)
    if not items:
        print("Recycle bin is empty."); sys.exit(0)

    def render_item(it):
        when = it.get("deletedDateTime") or ""
        by   = it.get("deletedBy") or ""
        loc  = it.get("deletedFromLocation") or ""
        return f"{it.get('name')}  |  id={it.get('id')}  |  deleted={when}  |  by={by}  |  from={loc}"

    item = prompt_choice(
        items,
        render_item,
        title="Recycle Bin Items"
    )
    rb_id  = item["id"]
    fname  = item.get("name")
    loc    = item.get("deletedFromLocation") or ""
    drive_rel = derive_drive_rel_path(loc)

    # 5) Restore via batch endpoint (your working pattern)
    print(f"\nRestoring: {fname}  (id={rb_id})")
    resp = batch_restore(site_id, token, [rb_id])
    echoed = [x.get("id") for x in (resp.get("value", []) if isinstance(resp, dict) else [])]
    if echoed and rb_id in echoed:
        print(f"[ok] Restore requested for id={rb_id} (batch restore).")
    else:
        print("[warn] Restore requested; API did not echo id (can be normal).")

    # 6) Verify + Download with polling
    print("\nVerifying restore and downloading the file (best effort)...")
    drive_item = wait_for_file(site_id, token, drive_rel, fname, attempts=6, sleep_sec=2)

    if drive_item:
        # parentReference.path like: /drive/root:/Shared%20Documents/Platform%20architecture/Processes
        pref = (drive_item.get("parentReference") or {}).get("path") or ""
        restored_path_hint = None
        if pref.startswith("/drive/root:/"):
            restored_path_hint = urllib.parse.unquote(pref[len("/drive/root:/"):].lstrip("/"))
        nm = drive_item.get("name") or fname
        try:
            local = download_file(site_id, token, drive_item, ".")
            print(f"[ok] Downloaded to: {local}")
        except Exception as e:
            print(f"[warn] Download failed: {e}")
        if restored_path_hint:
            print(f"[info] Restored to: {restored_path_hint}/{nm}")
        elif drive_rel:
            print(f"[info] Expected folder (from metadata): {drive_rel}/{nm}")
        else:
            print(f"[info] Restored file name: {nm} (location not resolved)")
    else:
        if drive_rel:
            print(f"[warn] Could not resolve restored file metadata yet.")
            print(f"[info] Expected folder (from metadata): {drive_rel}/{fname}")
        else:
            print("[warn] Could not resolve restored file metadata to download.")
    print("\nDone.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
