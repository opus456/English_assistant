from __future__ import annotations

import argparse
import email.utils
import json
import logging
import os
import re
import ssl
import time
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# 用来打印日志进行调试和检查
LOGGER = logging.getLogger("cet6_scraper")
# 设置伪装的访问身份
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
# 标签过滤器，确保文章的质量
TOPIC_KEYWORDS = {
    "science",
    "technology",
    "education",
    "culture",
    "society",
    "health",
    "environment",
    "economy",
    "policy",
}
# 对每个网站的结构定制抓取的标签策略
ARTICLE_SELECTORS = {
    "chinadaily.com.cn": [
        "#Content p",
        ".article p",
        "article p",
    ],
    "xinhuanet.com": [
        "#detail p",
        ".main-article p",
        "article p",
        "main p",
    ],
    "news.cn": [
        "#detail p",
        ".main-article p",
        "article p",
        "main p",
    ],
    "globaltimes.cn": [
        "div.article_right div.article_content p",
        "div.article_content p",
        "article p",
    ],
    "cgtn.com": [
        "div.cg-article-content p",
        "div.news-content p",
        "article p",
        "main p",
    ],
    "people.cn": [
        "div.w860 p",
        "div.rm_txt_con p",
        "article p",
        "main p",
    ],
    "ecns.cn": [
        "div#left_content p",
        ".left_content p",
        "article p",
    ],
    "shine.cn": [
        "div.article-content p",
        "article p",
        "main p",
    ],
}

# 抓取初步筛选（国内可直连）
FEEDS = [
    {
        "name": "China Daily Culture",
        "source": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/china_rss.xml",
        "topic": "society",
    },
    {
        "name": "China Daily World",
        "source": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/world_rss.xml",
        "topic": "society",
    },
    {
        "name": "China Daily Business",
        "source": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/bizchina_rss.xml",
        "topic": "economy",
    },
    {
        "name": "China Daily Culture",
        "source": "China Daily",
        "url": "https://www.chinadaily.com.cn/rss/culture_rss.xml",
        "topic": "culture",
    },
    {
        "name": "Xinhua World",
        "source": "Xinhua",
        "url": "http://www.xinhuanet.com/english/rss/worldrss.xml",
        "topic": "society",
    },
    {
        "name": "Xinhua Sci-Tech",
        "source": "Xinhua",
        "url": "http://www.xinhuanet.com/english/rss/sci-techrss.xml",
        "topic": "technology",
    },
    {
        "name": "Global Times Society",
        "source": "Global Times",
        "url": "https://www.globaltimes.cn/rss/china.xml",
        "topic": "society",
    },
    {
        "name": "CGTN World",
        "source": "CGTN",
        "url": "https://www.cgtn.com/subscribe/rss/section/world.xml",
        "topic": "society",
    },
    {
        "name": "CGTN Tech",
        "source": "CGTN",
        "url": "https://www.cgtn.com/subscribe/rss/section/tech.xml",
        "topic": "technology",
    },
    {
        "name": "People's Daily English",
        "source": "People's Daily",
        "url": "http://en.people.cn/rss/90000.xml",
        "topic": "society",
    },
    {
        "name": "ECNS",
        "source": "ECNS",
        "url": "http://www.ecns.cn/rss/rss.xml",
        "topic": "society",
    },
    {
        "name": "SHINE Shanghai",
        "source": "SHINE",
        "url": "https://www.shine.cn/rss/feed.xml",
        "topic": "culture",
    },
]

# 抓取的初步信息
@dataclass(slots=True)
class FeedEntry:
    title: str
    url: str
    source: str
    topic: str
    published_at: datetime | None

# 文章的进一步的信息
@dataclass(slots=True)
class ArticleCandidate:
    title: str
    url: str
    source: str
    topic: str
    published_at: datetime | None
    text: str
    word_count: int
    readability_score: float # 来判定文章难度是否合适进行打分
    difficulty_band: str

# 存放抓取的一些配置
@dataclass(slots=True)
class ScraperConfig:
    retries: int
    timeout_ms: int
    proxy_server: str | None
    ignore_https_errors: bool
    relax_feed_ssl: bool
    host_failure_threshold: int
    host_cooldown_seconds: int
    published_after: datetime | None
    published_before: datetime | None

today = date.today().strftime("%m-%d")
base_path = "./articles"
store_path = os.path.join(base_path,today)
os.makedirs(store_path,exist_ok=True)

#构建运行时候的命令行工具
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect CET-6 quality English articles into articles/test."
    )
    parser.add_argument(
        "--output-dir",
        default=f"articles/{today}",
        help="Directory used to store scraped article text and JSON files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum number of accepted articles to save.",
    )
    parser.add_argument(
        "--min-words",
        type=int,
        default=500,
        help="Minimum accepted word count.",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=800,
        help="Maximum accepted word count.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retry attempts for feed and page fetches.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=8000,
        help="Playwright page timeout in milliseconds.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level.",
    )
    parser.add_argument(
        "--proxy-server",
        default=None,
        help="Explicit proxy server, for example http://127.0.0.1:7897. Defaults to the system proxy env vars.",
    )
    parser.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="Ignore HTTPS certificate errors when loading article pages in the browser.",
    )
    parser.add_argument(
        "--relax-feed-ssl",
        action="store_true",
        help="Ignore HTTPS certificate errors when fetching RSS feeds.",
    )
    parser.add_argument(
        "--host-failure-threshold",
        type=int,
        default=2,
        help="Skip a host temporarily after this many article fetch failures.",
    )
    parser.add_argument(
        "--host-cooldown-seconds",
        type=int,
        default=180,
        help="How long to skip a host after repeated failures.",
    )
    parser.add_argument(
        "--published-after",
        default=None,
        help="Only keep articles published on or after this date, format YYYY-MM-DD.",
    )
    parser.add_argument(
        "--published-before",
        default=None,
        help="Only keep articles published on or before this date, format YYYY-MM-DD.",
    )
    parser.add_argument(
        "--recent-days",
        type=int,
        default=None,
        help="Only keep articles published within the last N days, including today.",
    )
    return parser

# 配置日志长什么样子
def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

# 传入代理如果没有的话就去系统里面找代理
def detect_proxy_server(explicit_proxy: str | None) -> str | None:
    if explicit_proxy:
        return explicit_proxy

    for key in ["HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"]:
        value = os.environ.get(key)
        if value:
            return value
    return None

# 获取ssl证书
def build_ssl_context(relax_ssl: bool) -> ssl.SSLContext:
    if relax_ssl: # 如果不需要就直接返回
        return ssl._create_unverified_context()

    cafile = os.environ.get("SSL_CERT_FILE") #查看系统中的证书
    if cafile:
        return ssl.create_default_context(cafile=cafile)

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where()) # 生成证书
    except ImportError:
        return ssl.create_default_context()

def fetch_url_text(url: str, retries: int, proxy_server: str | None, relax_ssl: bool) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    ssl_context = build_ssl_context(relax_ssl)
    handlers = [HTTPSHandler(context=ssl_context)]

    if proxy_server:
        handlers.insert(0, ProxyHandler({"http": proxy_server, "https": proxy_server}))
    opener = build_opener(*handlers)
    for attempt in range(1, retries + 1):
        try:
            with opener.open(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="ignore")
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            LOGGER.warning("Feed fetch failed (%s/%s) for %s: %s", attempt, retries, url, exc)
            time.sleep(min(attempt, 3))
    raise RuntimeError(f"Unable to fetch {url}") from last_error

def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)

def parse_cli_date(value: str | None, *, end_of_day: bool) -> datetime | None:
    if not value:
        return None
    parsed = datetime.strptime(value, "%Y-%m-%d")
    if end_of_day:
        return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed

def parse_entry_datetime(raw_value: str) -> datetime | None:
    value = normalize_whitespace(raw_value)
    if not value:
        return None

    try:
        return normalize_datetime(email.utils.parsedate_to_datetime(value))
    except (TypeError, ValueError, IndexError, OverflowError):
        pass

    for fmt in [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]:
        try:
            return normalize_datetime(datetime.strptime(value, fmt))
        except ValueError:
            continue
    return None

def within_publication_window(entry: FeedEntry, config: ScraperConfig) -> bool:
    if config.published_after is None and config.published_before is None:
        return True
    if entry.published_at is None:
        return False
    if config.published_after is not None and entry.published_at < config.published_after:
        return False
    if config.published_before is not None and entry.published_at > config.published_before:
        return False
    return True

# 获取rss里面的信息
def parse_rss_entries(feed_xml: str, source: str, topic: str) -> list[FeedEntry]:
    root = ET.fromstring(feed_xml)
    entries: list[FeedEntry] = []
    # 拿到所有的item里面的title和link
    for item in root.findall(".//item"): 
        title = normalize_whitespace(item.findtext("title", default=""))
        link = normalize_whitespace(item.findtext("link", default=""))
        published_at = parse_entry_datetime(
            item.findtext("pubDate", default="")
            or item.findtext("published", default="")
            or item.findtext("updated", default="")
        )
        if title and link:
            entries.append(
                FeedEntry(
                    title=title,
                    url=link,
                    source=source,
                    topic=topic,
                    published_at=published_at,
                )
            )

    if entries:
        return entries
    
    # 如果在之前没有找到的话就使用新的Atom协议继续找新的是使用entry
    namespace_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for item in namespace_items:
        title = normalize_whitespace(item.findtext("{http://www.w3.org/2005/Atom}title", default=""))
        link_node = item.find("{http://www.w3.org/2005/Atom}link")
        published_at = parse_entry_datetime(
            item.findtext("{http://www.w3.org/2005/Atom}published", default="")
            or item.findtext("{http://www.w3.org/2005/Atom}updated", default="")
        )
        link = ""
        if link_node is not None:
            link = normalize_whitespace(link_node.attrib.get("href", ""))
        if title and link:
            entries.append(
                FeedEntry(
                    title=title,
                    url=link,
                    source=source,
                    topic=topic,
                    published_at=published_at,
                )
            )

    return entries

def iter_feed_candidates(config: ScraperConfig) -> Iterable[FeedEntry]:
    for feed in FEEDS:
        try:
            # 得到xml结构
            feed_xml = fetch_url_text(
                feed["url"],
                retries=config.retries,
                proxy_server=config.proxy_server,
                relax_ssl=config.relax_feed_ssl,
            )
            # 得到要爬取的文章的信息
            entries = parse_rss_entries(
                feed_xml,
                source=feed["source"],
                topic=feed["topic"],
            )
        except Exception as exc:
            LOGGER.warning("Skip feed %s because %s", feed["name"], exc)
            continue
        # 根据title过滤文章
        for entry in entries:
            if topic_matches(entry.title, entry.topic) and within_publication_window(entry, config):
                yield entry

# 爬取文章
def scrape_article(page, entry: FeedEntry, timeout_ms: int, retries: int) -> ArticleCandidate | None:
    hostname = urlparse(entry.url).netloc.lower()
    selectors = ARTICLE_SELECTORS.get(hostname.replace("www.", ""), ["article p", "main p"]) #获取域名

    text = scrape_with_retry(page, entry.url, selectors, timeout_ms, retries)

    if not text:
        return None

    word_count = count_words(text)
    readability_score = estimate_cet6_score(text)
    difficulty_band = classify_difficulty(readability_score)

    return ArticleCandidate(
        title=entry.title,
        url=entry.url,
        source=entry.source,
        topic=entry.topic,
        published_at=entry.published_at,
        text=text,
        word_count=word_count,
        readability_score=readability_score,
        difficulty_band=difficulty_band,
    )

def scrape_with_retry(page, url: str, selectors: list[str], timeout_ms: int, retries: int) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            page.close()
        except PlaywrightError:
            pass
        page = page.context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            accept_common_popups(page)
            page.wait_for_timeout(600)
            text = extract_article_text(page, selectors)
            if text:
                page.close()
                return text
            raise RuntimeError("No article paragraphs extracted")
        except (PlaywrightTimeoutError, PlaywrightError, RuntimeError) as exc:
            last_error = exc
            LOGGER.warning(
                "Article fetch failed (%s/%s) for %s: %s",
                attempt,
                retries,
                url,
                exc,
            )
            try:
                page.close()
            except PlaywrightError:
                pass
            time.sleep(min(attempt, 2))
    LOGGER.error("Failed to scrape article %s", url)
    if last_error:
        LOGGER.debug("Last scrape error: %s", last_error)
    return ""

def accept_common_popups(page) -> None:
    for label in [
        "Accept",
        "I agree",
        "Yes, I agree",
        "Continue",
    ]:
        try:
            button = page.get_by_role("button", name=label)
            if button.count() > 0:
                button.first.click(timeout=1500)
                page.wait_for_timeout(500)
        except PlaywrightError:
            continue

def extract_article_text(page, selectors: list[str]) -> str:
    paragraphs: list[str] = []
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except PlaywrightError:
            continue

        if count == 0:
            continue

        current = []
        for index in range(count):
            try:
                paragraph = locator.nth(index).inner_text(timeout=1500)
            except PlaywrightError:
                continue
            paragraph = normalize_paragraph(paragraph)
            if is_good_paragraph(paragraph):
                current.append(paragraph)

        if len(current) >= 6:
            paragraphs = current
            break

    return "\n\n".join(paragraphs)

def normalize_paragraph(paragraph: str) -> str:
    paragraph = paragraph.replace("\xa0", " ")
    paragraph = normalize_whitespace(paragraph)
    return paragraph.strip()

def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def is_good_paragraph(paragraph: str) -> bool:
    if len(paragraph) < 40:
        return False
    lower = paragraph.lower()
    blocked_fragments = [
        "copyright",
        "sign up",
        "newsletter",
        "related topics",
        "read more",
    ]
    return not any(fragment in lower for fragment in blocked_fragments)

def count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text))

def split_sentences(text: str) -> list[str]:
    candidates = re.split(r"(?<=[.!?])\s+", text)
    return [item.strip() for item in candidates if item.strip()]

def estimate_cet6_score(text: str) -> float:
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
    sentences = split_sentences(text)
    if not words or not sentences:
        return 0.0

    avg_sentence_len = len(words) / max(len(sentences), 1)
    long_word_ratio = sum(1 for word in words if len(word) >= 8) / len(words)
    unique_ratio = len({word.lower() for word in words}) / len(words)
    score = avg_sentence_len * 1.8 + long_word_ratio * 40 + unique_ratio * 15
    return round(score, 2)

def classify_difficulty(score: float) -> str:
    if 58 <= score <= 80:
        return "CET-6 target"
    if score < 58:
        return "Below target"
    return "Above target"

def topic_matches(title: str, topic: str) -> bool:
    title_tokens = set(re.findall(r"[A-Za-z]+", title.lower()))
    return topic in title_tokens or topic in TOPIC_KEYWORDS

def candidate_accepted(candidate: ArticleCandidate, min_words: int, max_words: int) -> bool:
    if candidate.word_count < min_words or candidate.word_count > max_words:
        return False
    return candidate.difficulty_band == "CET-6 target"

def candidate_rank(candidate: ArticleCandidate, min_words: int, max_words: int) -> float:
    target_words = (min_words + max_words) / 2
    word_gap = abs(candidate.word_count - target_words)
    score_gap = abs(candidate.readability_score - 68)
    band_penalty = 0 if candidate.difficulty_band == "CET-6 target" else 20
    return word_gap + score_gap * 5 + band_penalty

def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "article"

def save_candidate(candidate: ArticleCandidate, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d")
    filename_stem = f"{timestamp}_{slugify(candidate.source)}_{slugify(candidate.title)[:50]}"
    text_path = output_dir / f"{filename_stem}.txt"
    metadata_path = output_dir / f"{filename_stem}.json"

    text_path.write_text(candidate.text + "\n", encoding="utf-8")
    metadata = {
        "title": candidate.title,
        "source": candidate.source,
        "url": candidate.url,
        "topic": candidate.topic,
        "published_at": candidate.published_at.isoformat(sep=" ") if candidate.published_at else None,
        "word_count": candidate.word_count,
        "readability_score": candidate.readability_score,
        "difficulty_band": candidate.difficulty_band,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return text_path, metadata_path

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)

    published_after = parse_cli_date(args.published_after, end_of_day=False)
    published_before = parse_cli_date(args.published_before, end_of_day=True)
    if args.recent_days is not None:
        if args.recent_days <= 0:
            raise SystemExit("--recent-days must be greater than 0")
        recent_window_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=args.recent_days - 1)
        if published_after is None or recent_window_start > published_after:
            published_after = recent_window_start
    if published_after and published_before and published_after > published_before:
        raise SystemExit("--published-after cannot be later than --published-before")

    proxy_server = detect_proxy_server(args.proxy_server)
    if proxy_server:
        LOGGER.info("Using proxy server %s", proxy_server)

    global CURRENT_CONFIG
    CURRENT_CONFIG = ScraperConfig(
        retries=args.retries,
        timeout_ms=args.timeout_ms,
        proxy_server=proxy_server,
        ignore_https_errors=args.ignore_https_errors,
        relax_feed_ssl=args.relax_feed_ssl,
        host_failure_threshold=args.host_failure_threshold,
        host_cooldown_seconds=args.host_cooldown_seconds,
        published_after=published_after,
        published_before=published_before,
    )

    output_dir = Path(args.output_dir)
    accepted = 0
    fallback_candidate: ArticleCandidate | None = None

    host_failures: dict[str, int] = {}
    host_blocked_until: dict[str, float] = {}

    with sync_playwright() as playwright:
        browser_kwargs = {"headless": True}
        if proxy_server:
            browser_kwargs["proxy"] = {"server": proxy_server}
        browser = playwright.chromium.launch(**browser_kwargs)
        context = browser.new_context(
            user_agent=USER_AGENT,
            ignore_https_errors=CURRENT_CONFIG.ignore_https_errors,
        )
        page = context.new_page()
        try:
            for entry in iter_feed_candidates(config=CURRENT_CONFIG):
                hostname = urlparse(entry.url).netloc.lower().replace("www.", "")
                blocked_until = host_blocked_until.get(hostname, 0.0)
                if blocked_until > time.time():
                    LOGGER.info("Skipping %s temporarily because recent fetches failed", hostname)
                    continue

                LOGGER.info("Inspecting %s | %s", entry.source, entry.title)
                candidate = scrape_article(page, entry, timeout_ms=args.timeout_ms, retries=args.retries)
                if candidate is None:
                    failures = host_failures.get(hostname, 0) + 1
                    host_failures[hostname] = failures
                    if failures >= CURRENT_CONFIG.host_failure_threshold:
                        host_blocked_until[hostname] = time.time() + CURRENT_CONFIG.host_cooldown_seconds
                        LOGGER.warning(
                            "Skipping host %s for %s seconds after %s failures",
                            hostname,
                            CURRENT_CONFIG.host_cooldown_seconds,
                            failures,
                        )
                    continue

                host_failures[hostname] = 0

                LOGGER.info(
                    "Scored article word_count=%s readability=%s difficulty=%s",
                    candidate.word_count,
                    candidate.readability_score,
                    candidate.difficulty_band,
                )

                if not candidate_accepted(candidate, args.min_words, args.max_words):
                    if fallback_candidate is None or candidate_rank(candidate, args.min_words, args.max_words) < candidate_rank(
                        fallback_candidate,
                        args.min_words,
                        args.max_words,
                    ):
                        fallback_candidate = candidate
                    continue

                text_path, metadata_path = save_candidate(candidate, output_dir)
                accepted += 1
                LOGGER.info("Saved text to %s", text_path)
                LOGGER.info("Saved metadata to %s", metadata_path)

                if accepted >= args.limit:
                    break
        finally:
            try:
                page.close()
            except PlaywrightError:
                pass
            context.close()
            browser.close()

    if accepted == 0 and fallback_candidate is not None:
        text_path, metadata_path = save_candidate(fallback_candidate, output_dir)
        LOGGER.warning(
            "No article met all strict filters; saved the closest match with word_count=%s readability=%s difficulty=%s",
            fallback_candidate.word_count,
            fallback_candidate.readability_score,
            fallback_candidate.difficulty_band,
        )
        LOGGER.info("Saved text to %s", text_path)
        LOGGER.info("Saved metadata to %s", metadata_path)
        return 0

    if accepted == 0:
        LOGGER.error("No articles matched the current constraints.")
        return 1

    LOGGER.info("Saved %s article(s) into %s", accepted, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())