"""Official page -> linked ATS board -> documented read-only postings API.

No guessed board slugs, arbitrary URL endpoint, browser execution or submissions.
"""
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "JobPipeline/2.0"
BOARD_HOSTS = {
    "boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
    "boards.eu.greenhouse.io": "greenhouse-eu", "job-boards.eu.greenhouse.io": "greenhouse-eu",
    "jobs.lever.co": "lever", "jobs.eu.lever.co": "lever-eu", "jobs.ashbyhq.com": "ashby",
}
API_HOSTS = {"boards-api.greenhouse.io", "boards-api.eu.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.ashbyhq.com"}


class SourceError(ValueError):
    pass


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        self.parts.append(" ")
        if tag in ("a", "iframe", "script"):
            value = dict(attrs).get("href" if tag == "a" else "src")
            if value:
                self.links.append(value)

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value):
    parser = PageParser()
    parser.feed(unescape(str(value or "")))
    return " ".join(" ".join(parser.parts).split())


def public_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.port not in (None, 443)):
        raise SourceError("Only public HTTPS sources on port 443 are supported")
    try:
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SourceError("Source hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise SourceError("Private, loopback and reserved network sources are blocked")


class Fetcher:
    """Bound response size, requests, retries and elapsed time for each company."""
    def __init__(self):
        self.client = httpx.Client(timeout=12, follow_redirects=False, trust_env=False,
                                   headers={"User-Agent": USER_AGENT})
        self.deadline = time.monotonic() + 90
        self.requests = 0
        self.robots = {}

    def close(self):
        self.client.close()

    def request(self, url):
        public_url(url)
        for attempt in range(2):
            if self.requests >= 20 or time.monotonic() >= self.deadline:
                raise SourceError("Company request/time budget reached; try a smaller pilot")
            self.requests += 1
            try:
                with self.client.stream("GET", url) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 0:
                            # Never exceed the provider's Retry-After by retrying earlier.
                            wait = response.headers.get("Retry-After", "1")
                            if not wait.isdigit() or int(wait) > 3:
                                raise SourceError("Source asks for a later retry; run discovery later")
                            time.sleep(max(1, int(wait)))
                            continue
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 8 * 1024 * 1024 or time.monotonic() >= self.deadline:
                            raise SourceError("Source response exceeds the size/time budget")
                    return response.status_code, response.headers, bytes(chunks)
            except httpx.HTTPError as exc:
                raise SourceError(f"Source network error: {type(exc).__name__}") from exc
        raise SourceError("Source retry budget exhausted")

    def permitted(self, url):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            robots_url = origin + "/robots.txt"
            aliases = {parts.hostname, parts.hostname.removeprefix("www."), "www." + parts.hostname.removeprefix("www.")}
            for _ in range(4):
                status, headers, content = self.request(robots_url)
                if status not in (301, 302, 303, 307, 308):
                    break
                robots_url = urljoin(robots_url, headers.get("location", ""))
                if urlsplit(robots_url).hostname not in aliases:
                    raise SourceError("robots.txt redirect leaves the official host/www alias")
            parser = RobotFileParser()
            if status in (404, 410):
                parser.parse(["User-agent: *", "Allow: /"])
            elif status == 200:
                parser.parse(content.decode("utf-8", errors="replace").splitlines())
            else:
                raise SourceError(f"Cannot verify robots.txt (HTTP {status}); source skipped")
            self.robots[origin] = parser
        parser = self.robots[origin]
        if not parser.can_fetch(USER_AGENT, url):
            raise SourceError("Source disallows this URL in robots.txt")
        delay = parser.crawl_delay(USER_AGENT) or 0
        if delay > 3:
            raise SourceError("Source crawl delay exceeds pilot budget")
        if delay:
            time.sleep(delay)

    def get(self, url, allowed_hosts, public_api=False):
        for _ in range(5):
            if urlsplit(url).hostname not in allowed_hosts:
                raise SourceError("Redirect leaves the official source or supported ATS hosts")
            if public_api:
                if urlsplit(url).hostname not in API_HOSTS:
                    raise SourceError("Not a supported public postings API host")
            else:
                self.permitted(url)
            status, headers, content = self.request(url)
            if status in (301, 302, 303, 307, 308):
                url = urljoin(url, headers.get("location", ""))
                continue
            if status != 200:
                raise SourceError(f"Source returned HTTP {status}")
            return url, content
        raise SourceError("Too many source redirects")


@dataclass(frozen=True)
class Board:
    provider: str
    token: str
    url: str


def board_from_url(url):
    parts = urlsplit(url)
    provider = BOARD_HOSTS.get(parts.hostname)
    if not provider or parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        return None
    segments = parts.path.strip("/").split("/")
    token = segments[0]
    if token == "embed" and provider.startswith("greenhouse"):
        token = parse_qs(parts.query).get("for", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", token):
        return None
    return Board(provider, token, f"https://{parts.hostname}/{token}")


def resolve_board(career_page, fetcher):
    direct = board_from_url(career_page)
    if direct:
        return direct
    host = urlsplit(career_page).hostname or ""
    aliases = {host, host.removeprefix("www."), "www." + host.removeprefix("www."), *BOARD_HOSTS}
    final_url, content = fetcher.get(career_page, aliases)
    direct = board_from_url(final_url)
    if direct:
        return direct
    parser = PageParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    boards = {board for link in parser.links if (board := board_from_url(urljoin(final_url, link)))}
    if len(boards) != 1:
        raise SourceError("Unsupported career page: expected one linked Greenhouse, Lever or Ashby board")
    return boards.pop()


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise SourceError("Posting has an invalid HTTPS source URL")
    # Custom Greenhouse pages can identify a job with ?gh_jid=123. Preserve all
    # unknown/identity parameters; remove only recognized tracking parameters.
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.casefold().startswith("utm_")
             and key.casefold() not in {"gh_src", "lever-source", "lever-origin"}]
    return urlunsplit(("https", parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), ""))


def normalize_job(raw, board):
    if board.provider.startswith("greenhouse"):
        title, identifier, url = raw["title"], raw["id"], raw["absolute_url"]
        location = (raw.get("location") or {}).get("name", "")
        description = plain_text(raw.get("content"))
    elif board.provider.startswith("lever"):
        title, identifier, url = raw["text"], raw["id"], raw["hostedUrl"]
        categories = raw.get("categories") or {}
        location = "; ".join(categories.get("allLocations") or [categories.get("location", "")])
        description = plain_text(" ".join([raw.get("descriptionPlain") or raw.get("description") or "",
            *[str(item.get("text", "")) + " " + str(item.get("content", "")) for item in raw.get("lists", [])],
            raw.get("additionalPlain") or raw.get("additional") or ""]))
    else:
        title, url = raw["title"], raw["jobUrl"]
        identifier = urlsplit(url).path.rstrip("/").split("/")[-1]
        location = "; ".join([raw.get("location") or "", *[
            item.get("location", "") for item in raw.get("secondaryLocations", [])]])
        description = plain_text(raw.get("descriptionPlain") or raw.get("descriptionHtml"))
    if not isinstance(title, str) or not title.strip() or not str(identifier).strip():
        raise SourceError("Posting is missing title or provider ID")
    return {"external_id": str(identifier), "title": title.strip(), "location": location,
            "description": description, "url": canonical_url(url)}


def fetch_jobs(board, fetcher, limit):
    if board.provider.startswith("greenhouse"):
        host = "boards-api.eu.greenhouse.io" if board.provider.endswith("-eu") else "boards-api.greenhouse.io"
        endpoint = f"https://{host}/v1/boards/{board.token}/jobs?content=true"
    elif board.provider.startswith("lever"):
        host = "api.eu.lever.co" if board.provider.endswith("-eu") else "api.lever.co"
        endpoint = f"https://{host}/v0/postings/{board.token}?mode=json&limit=100&skip="
    else:
        host = "api.ashbyhq.com"
        endpoint = f"https://{host}/posting-api/job-board/{board.token}"
    records = []
    truncated = False
    offset = 0
    while True:
        _, content = fetcher.get(endpoint + str(offset) if board.provider.startswith("lever") else endpoint, {host}, public_api=True)
        try:
            data = json.loads(content)
            page = data if board.provider.startswith("lever") else data["jobs"]
            if not isinstance(page, list):
                raise TypeError("jobs must be a list")
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError("Source returned an unexpected JSON job list") from exc
        listed = [raw for raw in page if not isinstance(raw, dict) or raw.get("isListed", True)]
        records.extend(listed)
        if len(records) >= limit:
            truncated = len(records) > limit or (board.provider.startswith("lever") and len(page) == 100)
            break
        if not board.provider.startswith("lever") or len(page) < 100:
            break
        offset += 100
    jobs, errors = [], []
    for index, raw in enumerate(records[:limit]):
        try:
            jobs.append(normalize_job(raw, board))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            errors.append(f"Posting {index + 1}: {type(exc).__name__}: {str(exc)[:160]}")
    return jobs, errors, truncated
