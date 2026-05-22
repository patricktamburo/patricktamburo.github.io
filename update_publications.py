#!/usr/bin/env python3
"""
update_publications.py

Queries the ADS API for publications by Tamburo, P. and rewrites the
Key Publications list in index.html.

Requirements:
    pip install requests

ADS API token (get one at https://ui.adsabs.harvard.edu/ → Account → API Token):
    Option 1: export ADS_TOKEN=your_token_here
    Option 2: save the token (just the token string) to ~/.ads/token

Usage:
    python update_publications.py
"""

import os
import re
import sys

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AUTHOR_QUERY = 'author:"Tamburo, P."'
ADS_SEARCH_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_LIBRARY_ID = "RaZPacIVQW6Tv521EswTvQ"
ADS_LIBRARY_URL = f"https://ui.adsabs.harvard.edu/public-libraries/{ADS_LIBRARY_ID}"
ADS_LIBRARY_API = f"https://api.adsabs.harvard.edu/v1/biblib/libraries/{ADS_LIBRARY_ID}"

# Show all authors when the list is this long or shorter; otherwise use et al.
MAX_AUTHORS_BEFORE_ETAL = 5

# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


def get_token():
    token = os.environ.get("ADS_TOKEN", "").strip()
    if token:
        return token
    path = os.path.expanduser("~/.ads/token")
    if os.path.exists(path):
        return open(path).read().strip()
    sys.exit(
        "ADS API token not found.\n"
        "  Option 1: export ADS_TOKEN=<your_token>\n"
        "  Option 2: save the token to ~/.ads/token\n"
        "Get a token at https://ui.adsabs.harvard.edu/ → Account → API Token"
    )


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_library_count(token):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(ADS_LIBRARY_API, headers=headers, params={"rows": 0})
    r.raise_for_status()
    return r.json()["metadata"]["num_documents"]


def fetch_publications(token):
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "q": AUTHOR_QUERY,
        "fl": "author,year,title,bibcode,pub,volume,page,identifier,doctype",
        "fq": "doctype:(article OR eprint)",
        "sort": "date desc, bibcode desc",
        "rows": 200,
    }
    r = requests.get(ADS_SEARCH_URL, headers=headers, params=params)
    r.raise_for_status()
    docs = r.json()["response"]["docs"]

    # Keep only papers where Tamburo appears in the first three authors.
    def tamburo_in_first_three(doc):
        authors = doc.get("author") or []
        return any("Tamburo" in a for a in authors[:3])

    docs = [doc for doc in docs if tamburo_in_first_three(doc)]

    # If a preprint has since been published (same title), drop the preprint.
    published_titles = {
        doc["title"][0].lower()
        for doc in docs
        if doc.get("doctype") == "article" and doc.get("title")
    }
    return [
        doc for doc in docs
        if not (
            doc.get("doctype") == "eprint"
            and (doc.get("title") or [""])[0].lower() in published_titles
        )
    ]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def abbreviate(name):
    """'García-Mejía, Juliana Rose' → 'García-Mejía, J. R.'"""
    parts = name.split(", ", 1)
    if len(parts) == 1:
        return name
    last, firsts = parts
    initials = " ".join(w[0] + "." for w in firsts.split() if w)
    return f"{last}, {initials}"


def format_authors(authors):
    """Comma-separated list, Tamburo bolded, et al. for long lists."""
    formatted = []
    tamburo_idx = None
    for i, a in enumerate(authors):
        fa = abbreviate(a)
        if "Tamburo" in a:
            fa = f"<strong>{fa}</strong>"
            tamburo_idx = i
        formatted.append(fa)

    n = len(formatted)

    if n <= MAX_AUTHORS_BEFORE_ETAL:
        if n == 1:
            return formatted[0]
        if n == 2:
            return f"{formatted[0]} and {formatted[1]}"
        return ", ".join(formatted[:-1]) + ", and " + formatted[-1]

    # Long list: first 3 authors + et al., always keeping Tamburo visible.
    shown = list(formatted[:3])
    if tamburo_idx is not None and tamburo_idx >= 3:
        shown.append(formatted[tamburo_idx])
    shown.append("et al.")
    return ", ".join(shown)


def arxiv_id(identifiers):
    for ident in identifiers or []:
        if ident.startswith("arXiv:"):
            return ident[len("arXiv:"):]
    return None


def format_journal(doc):
    pub = doc.get("pub") or ""
    volume = doc.get("volume") or ""
    page_raw = doc.get("page") or ""
    page = page_raw[0] if isinstance(page_raw, list) else page_raw
    arxiv = arxiv_id(doc.get("identifier", []))

    # Prefer arXiv citation style for preprints or when no volume exists.
    if arxiv and (not volume or "arXiv" in pub):
        return f"arXiv e-prints, arXiv:{arxiv}"

    return ", ".join(p for p in [pub, volume, page] if p)


def render_li(doc):
    authors = format_authors(doc.get("author") or [])
    year = doc.get("year", "")
    title = (doc.get("title") or ["(no title)"])[0]
    url = f"https://ui.adsabs.harvard.edu/abs/{doc['bibcode']}"
    journal = format_journal(doc)

    return (
        f'\t\t\t\t\t\t\t<li> <span> {authors}, {year}. '
        f'<a href="{url}" target="blank">"{title}"</a>. '
        f'{journal}. </span> </li> <br>\n'
    )


# ---------------------------------------------------------------------------
# HTML injection
# ---------------------------------------------------------------------------

_OL_PATTERN = re.compile(
    r'(<ol type="1">)(.*?)(</ol>)',
    re.DOTALL,
)


def build_ol_body(docs, library_count):
    items = "".join(render_li(doc) for doc in docs)
    footer = (
        "\n"
        "\t\t\t\t\t\t\t<br>\n"
        f"\t\t\t\t\t\t\t<p><strong>A full listing of my {library_count} refereed "
        f'publications is available on <a href="{ADS_LIBRARY_URL}" target="blank">'
        "SAO/NASA ADS</a>.</strong></p>\n"
        "\t\t\t\t\t\t"
    )
    return f"\n{items}{footer}"


def update_html(html, docs, library_count):
    if not _OL_PATTERN.search(html):
        sys.exit('Could not find <ol type="1">…</ol> in index.html.')
    new_body = build_ol_body(docs, library_count)
    return _OL_PATTERN.sub(
        lambda m: m.group(1) + new_body + m.group(3),
        html,
        count=1,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    token = get_token()

    print("Querying ADS...", end=" ", flush=True)
    docs = fetch_publications(token)
    print(f"{len(docs)} selected publications.")

    print("Fetching library count...", end=" ", flush=True)
    library_count = fetch_library_count(token)
    print(f"{library_count} refereed publications in library.")

    here = os.path.dirname(os.path.abspath(__file__))
    index_path = os.path.join(here, "index.html")

    with open(index_path) as f:
        html = f.read()

    new_html = update_html(html, docs, library_count)

    with open(index_path, "w") as f:
        f.write(new_html)

    print(f"Wrote {index_path}")


if __name__ == "__main__":
    main()
