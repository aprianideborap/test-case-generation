#!/usr/bin/env python3
"""
Fetch a Confluence page's content via the REST API (Server/Data Center,
Bearer-token auth) and print it as readable text/markdown. Optionally
downloads every image embedded in the page body (screenshots, flow diagrams)
so they can be viewed directly.

Reads credentials from CONFLUENCE_TOKEN / CONFLUENCE_BASE_URL env vars, or a local config file (default: ../config.json,
gitignored) shaped like:
    {
        "base_url": "https://confluence.shopee.io",
        "token": "<personal access token>"
    }

Usage:
    python3 fetch_confluence_page.py --url "https://confluence.shopee.io/display/TEAM/My+Page"
    python3 fetch_confluence_page.py --url "..." --output page.md
    python3 fetch_confluence_page.py --url "..." --images-dir ./page-images
"""
import argparse
import json
import os
import re
import stat
import sys
from urllib.parse import unquote, urlparse, parse_qs

try:
    import requests
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    sys.exit(
        "requests and beautifulsoup4 are required but not installed.\n"
        "If pip install fails with an 'externally-managed-environment' error, use a venv:\n"
        "  V=$(mktemp -d)/venv && python3 -m venv $V && $V/bin/pip install --quiet requests beautifulsoup4\n"
        "  $V/bin/python3 fetch_confluence_page.py ...\n"
    )

DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "..", "config.json")


def load_config(config_path):
    """Token precedence: CONFLUENCE_TOKEN env var, then config.json.
    base_url precedence: CONFLUENCE_BASE_URL env var, then config.json."""
    cfg = {}
    if os.path.exists(config_path):
        mode = os.stat(config_path).st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(
                f"Warning: {config_path} is readable by other users; run: chmod 600 {config_path}",
                file=sys.stderr,
            )
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    base_url = (os.environ.get("CONFLUENCE_BASE_URL") or cfg.get("base_url", "")).rstrip("/")
    token = os.environ.get("CONFLUENCE_TOKEN") or cfg.get("token", "")
    if not base_url or not token or token.startswith("<"):
        sys.exit(
            "Confluence credentials not found. Set CONFLUENCE_TOKEN (and optionally "
            "CONFLUENCE_BASE_URL) in your environment, or copy config.example.json to "
            "config.json and fill in a real Personal Access Token."
        )
    if urlparse(base_url).scheme != "https":
        sys.exit("base_url must use https:// — refusing to send the token over plain HTTP.")
    return base_url, token


def same_origin(base_url, url):
    a, b = urlparse(base_url), urlparse(url)
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def safe_filename(name):
    """Strip any directory components / odd characters from an
    attacker-controllable filename so it can't escape the images dir."""
    name = os.path.basename(name.replace("\\", "/").split("?")[0])
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).lstrip(".")
    return name[:120] or "image"


def extract_page_id(url):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "pageId" in qs:
        return qs["pageId"][0]
    m = re.search(r"/pages/(\d+)", parsed.path)
    if m:
        return m.group(1)
    return None


def extract_space_and_title(url):
    parsed = urlparse(url)
    m = re.search(r"/display/([^/]+)/([^/?]+)", parsed.path)
    if m:
        space, title = m.groups()
        return space, unquote(title).replace("+", " ")
    return None, None


def fetch_page(base_url, token, url):
    if not same_origin(base_url, url):
        sys.exit(f"Refusing to fetch {url}: it is not on the configured Confluence host ({base_url}).")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    page_id = extract_page_id(url)
    try:
        if page_id:
            resp = requests.get(
                f"{base_url}/rest/api/content/{page_id}",
                headers=headers,
                params={"expand": "body.storage,version,space"},
                timeout=30,
            )
        else:
            space, title = extract_space_and_title(url)
            if not (space and title):
                sys.exit(
                    f"Could not extract a pageId or space/title from URL: {url}\n"
                    "Pass a direct page link (contains '?pageId=NNN' or '/pages/NNN/...' or '/display/SPACE/Title')."
                )
            resp = requests.get(
                f"{base_url}/rest/api/content",
                headers=headers,
                params={"spaceKey": space, "title": title, "expand": "body.storage,version,space"},
                timeout=30,
            )
    except requests.exceptions.RequestException as e:
        sys.exit(f"Request to Confluence failed: {e}")

    if resp.status_code in (401, 403):
        sys.exit(
            f"Confluence returned {resp.status_code} — the Personal Access Token in config.json "
            "is missing, expired, or lacks permission to view this page."
        )
    if resp.status_code == 404:
        sys.exit(f"Confluence returned 404 — page not found (check the URL / permissions): {url}")
    resp.raise_for_status()

    data = resp.json()
    if "results" in data:
        if not data["results"]:
            sys.exit(f"No page found for the space/title extracted from URL: {url}")
        data = data["results"][0]
    return data


def inline_text(node):
    """Like get_text(), but keeps <a href> targets instead of dropping them —
    hyperlinked text in a PRD often carries a reference URL worth keeping."""
    if isinstance(node, NavigableString):
        return str(node)
    name = getattr(node, "name", None)
    if name == "a":
        href = node.get("href", "")
        text = "".join(inline_text(c) for c in node.children).strip()
        if href and href not in text:
            return f"{text} ({href})".strip() if text else href
        return text or href
    if name == "br":
        return " "
    if name == "ac:image":
        label = image_label(node)
        return f" [IMAGE: {label}] " if label else ""
    if name == "img":
        src = node.get("src", "")
        return f" [IMAGE: {src}] " if src else ""
    return "".join(inline_text(c) for c in getattr(node, "children", []))


def clean_inline(node):
    return re.sub(r"\s+", " ", inline_text(node)).strip()


def node_to_markdown(node, depth=0):
    if isinstance(node, NavigableString):
        return ""
    name = getattr(node, "name", None)
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(name[1])
        return "\n" + "#" * level + " " + clean_inline(node) + "\n"
    if name == "p":
        text = clean_inline(node)
        return text + "\n" if text else ""
    if name in ("ul", "ol"):
        lines = []
        for i, li in enumerate(node.find_all("li", recursive=False), start=1):
            bullet = f"{i}." if name == "ol" else "-"
            lines.append(f"{'  ' * depth}{bullet} {clean_inline(li)}")
        lines.append("")
        return "\n".join(lines)
    if name == "table":
        lines = []
        for row in node.find_all("tr"):
            cells = row.find_all(["th", "td"])
            lines.append("| " + " | ".join(clean_inline(c) for c in cells) + " |")
        lines.append("")
        return "\n".join(lines)
    if name == "br":
        return "\n"
    if name == "ac:image":
        label = image_label(node)
        return f"\n[IMAGE: {label}]\n" if label else ""
    if name == "img":
        src = node.get("src", "")
        return f"\n[IMAGE: {src}]\n" if src else ""
    # container we don't special-case: recurse into children
    parts = [node_to_markdown(child, depth) for child in getattr(node, "children", [])]
    return "\n".join(p for p in parts if p)


def image_label(ac_image_node):
    """Return the referenced filename (attachment) or URL (external) for an
    <ac:image> macro, or None if it has neither."""
    att = ac_image_node.find("ri:attachment")
    if att and att.get("ri:filename"):
        return att["ri:filename"]
    url_tag = ac_image_node.find("ri:url")
    if url_tag and url_tag.get("ri:value"):
        return url_tag["ri:value"]
    return None


def extract_image_refs(html):
    """Ordered, de-duplicated list of (kind, value) for every image referenced
    in the page body: ("attachment", filename) or ("url", external url)."""
    soup = BeautifulSoup(html, "html.parser")
    refs = []
    seen = set()

    def add(kind, value):
        key = (kind, value)
        if value and key not in seen:
            seen.add(key)
            refs.append(key)

    for node in soup.find_all("ac:image"):
        att = node.find("ri:attachment")
        url_tag = node.find("ri:url")
        if att and att.get("ri:filename"):
            add("attachment", att["ri:filename"])
        elif url_tag and url_tag.get("ri:value"):
            add("url", url_tag["ri:value"])
    for node in soup.find_all("img"):
        add("url", node.get("src", ""))
    return refs


def storage_html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")
    root = soup.body or soup
    text = node_to_markdown(root)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def list_attachments(base_url, token, page_id):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = requests.get(
        f"{base_url}/rest/api/content/{page_id}/child/attachment",
        headers=headers,
        params={"limit": 200},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


MAX_IMAGE_BYTES = 20 * 1024 * 1024


def download_file(url, dest_path, headers=None):
    # Never follow redirects: the Authorization header must only go to the
    # Confluence host, and a redirect could point anywhere.
    with requests.get(url, headers=headers or {}, timeout=60, stream=True, allow_redirects=False) as resp:
        resp.raise_for_status()
        if resp.is_redirect:
            raise requests.exceptions.RequestException("unexpected redirect")
        ctype = resp.headers.get("Content-Type", "")
        if not ctype.lower().startswith("image/"):
            raise requests.exceptions.RequestException(f"not an image (Content-Type: {ctype or 'missing'})")
        total = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(65536):
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise requests.exceptions.RequestException("image exceeds 20 MB limit")
                f.write(chunk)


def download_images(base_url, token, page_id, image_refs, images_dir):
    """Download every referenced image into images_dir. Returns a list of
    (label, local_path) for images that downloaded successfully."""
    os.makedirs(images_dir, exist_ok=True)
    auth_headers = {"Authorization": f"Bearer {token}"}

    attachments_by_filename = {}
    if any(kind == "attachment" for kind, _ in image_refs):
        try:
            attachments_by_filename = {a.get("title"): a for a in list_attachments(base_url, token, page_id)}
        except requests.exceptions.RequestException as e:
            print(f"Warning: could not list page attachments: {e}", file=sys.stderr)

    downloaded = []
    for kind, value in image_refs:
        try:
            if kind == "attachment":
                att = attachments_by_filename.get(value)
                link = att.get("_links", {}).get("download") if att else None
                if not link:
                    print(f"Warning: attachment '{value}' not found on this page, skipping.", file=sys.stderr)
                    continue
                url = link if link.startswith("http") else base_url + link
                if not same_origin(base_url, url):
                    print(f"Warning: attachment '{value}' points off-host, skipping.", file=sys.stderr)
                    continue
                dest = os.path.join(images_dir, safe_filename(value))
                download_file(url, dest, headers=auth_headers)
            else:
                # External image URLs come from untrusted page content; fetching
                # them would allow SSRF / tracking, so they are never downloaded.
                print(f"Skipped external image (not downloaded): {value}", file=sys.stderr)
                continue
            downloaded.append((value, dest))
        except requests.exceptions.RequestException as e:
            print(f"Warning: failed to download image '{value}': {e}", file=sys.stderr)
    return downloaded


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", required=True, help="Confluence page URL")
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="Path to config.json")
    ap.add_argument("--output", help="Save extracted text to this file instead of printing to stdout")
    ap.add_argument(
        "--images-dir",
        help="Download every image referenced in the page body into this directory "
        "(screenshots/flow diagrams embedded via Confluence's image macro). "
        "View the downloaded files with the Read tool to use them as context.",
    )
    args = ap.parse_args()

    base_url, token = load_config(args.config)
    data = fetch_page(base_url, token, args.url)

    title = data.get("title", "Untitled")
    html = data.get("body", {}).get("storage", {}).get("value", "")
    if not html:
        sys.exit("Page fetched but no body content found (check the 'expand' params or page permissions).")

    text = storage_html_to_text(html)
    result = f"# {title}\n\n{text}"

    if args.images_dir:
        image_refs = extract_image_refs(html)
        if image_refs:
            downloaded = download_images(base_url, token, data.get("id"), image_refs, args.images_dir)
            if downloaded:
                result += "\n\n## Embedded Images (downloaded for visual review)\n"
                for label, path in downloaded:
                    result += f"- {label} -> {path}\n"

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Saved page content to {args.output}")
    else:
        print(result)


if __name__ == "__main__":
    main()
