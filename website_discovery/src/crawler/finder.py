"""
Domain Finder module for extracting domains from URLs.

This module provides functionality to:
    - Parse HTML content and extract links
    - Extract domains from URLs
    - Filter for .gov.bd domains only
    - Normalize and deduplicate domains

Usage:
    >>> from src.crawler.finder import DomainFinder
    >>> finder = DomainFinder()
    >>> domains = finder.extract_domains("https://example.gov.bd/page")
"""

from __future__ import annotations

import asyncio

import aiohttp
from bs4 import BeautifulSoup
from loguru import logger

from src.config.settings import settings
from src.database.models import Domain


class DomainFinder:
    """
    Extracts domains from URLs and HTML content.

    This class handles:
    - HTML parsing for link extraction
    - Domain normalization (removing www, protocol, etc.)
    - .gov.bd domain filtering
    - Duplicate detection

    Attributes:
        allowed_tlds: List of allowed top-level domains.
        excluded_tags: HTML tags to skip during parsing.

    Example:
        >>> finder = DomainFinder()
        >>> domains = await finder.find_from_url("https://bangladesh.gov.bd")
    """

    def __init__(
        self,
        allowed_tlds: list[str] | None = None,
        excluded_tags: list[str] | None = None,
    ) -> None:
        """
        Initialize DomainFinder.

        Args:
            allowed_tlds: List of allowed TLDs. Defaults to .gov.bd.
            excluded_tags: HTML tags to exclude. Defaults to nav, footer, etc.
        """
        self.allowed_tlds: list[str] = allowed_tlds or settings.crawler.allowed_tlds
        self.excluded_tags: list[str] = excluded_tags or settings.crawler.excluded_tags
        self.normalize_urls: bool = settings.crawler.normalize_urls
        self.strip_fragment: bool = settings.crawler.strip_fragment
        self.lowercase_domains: bool = settings.crawler.lowercase_domains

        logger.debug(f"DomainFinder initialized with TLDs: {self.allowed_tlds}")

    def normalize_url(self, url: str) -> str:
        """
        Normalize a URL to a consistent format.

        Removes protocol, www. prefix, trailing slashes, and fragments.
        Converts domain to lowercase.

        Args:
            url: The URL to normalize.

        Returns:
            Normalized URL without protocol, www., or fragment.

        Example:
            >>> finder = DomainFinder()
            >>> finder.normalize_url("https://www.example.gov.bd/page#section")
            'example.gov.bd/page'
        """
        from urllib.parse import urlparse

        if not url:
            return url

        try:
            parsed = urlparse(url)

            # Remove fragment if stripping enabled
            if self.strip_fragment:
                parsed = parsed._replace(fragment="")

            # Reconstruct URL without scheme
            netloc = parsed.netloc
            if self.lowercase_domains:
                netloc = netloc.lower()

            # Remove www. prefix
            if netloc.startswith("www."):
                netloc = netloc[4:]

            # Remove port
            if ":" in netloc:
                netloc = netloc.split(":")[0]

            # Rebuild path
            path = parsed.path
            if self.normalize_urls:
                # Remove duplicate slashes
                while "//" in path:
                    path = path.replace("//", "/")

            result = f"{netloc}{path}"
            if parsed.query:
                result += f"?{parsed.query}"

            return result

        except Exception as e:
            logger.debug(f"Failed to normalize URL {url}: {e}")
            return url

    def normalize_domain(self, domain: str) -> str:
        """
        Normalize a domain name.

        Removes protocol, www. prefix, and trailing dots.
        Converts to lowercase.

        Args:
            domain: Domain name to normalize.

        Returns:
            Normalized domain name.

        Example:
            >>> finder = DomainFinder()
            >>> finder.normalize_domain("WWW.Example.GOV.BD")
            'example.gov.bd'
        """
        if not domain:
            return ""

        # Remove protocol
        for prefix in ("http://", "https://"):
            domain = domain.replace(prefix, "")

        # Remove www.
        if domain.startswith("www."):
            domain = domain[4:]

        # Remove trailing dots
        domain = domain.rstrip(".")

        # Lowercase
        if self.lowercase_domains:
            domain = domain.lower()

        # Remove port
        if ":" in domain:
            domain = domain.split(":")[0]

        # Remove path (everything after /)
        if "/" in domain:
            domain = domain.split("/")[0]

        return domain.strip()

    def is_allowed_domain(self, domain: str) -> bool:
        """
        Check if domain has an allowed TLD.

        Args:
            domain: Domain name to check.

        Returns:
            True if domain has an allowed TLD.

        Example:
            >>> finder = DomainFinder()
            >>> finder.is_allowed_domain("example.gov.bd")
            True
            >>> finder.is_allowed_domain("example.com")
            False
        """
        normalized = self.normalize_domain(domain)

        for tld in self.allowed_tlds:
            if normalized.endswith(tld):
                return True

        return False

    def is_excluded_tag(self, tag: str) -> bool:
        """
        Check if HTML tag should be excluded.

        Args:
            tag: HTML tag name.

        Returns:
            True if tag should be skipped.
        """
        return tag.lower() in [t.lower() for t in self.excluded_tags]

    async def fetch_url_content(
        self,
        url: str,
        session: aiohttp.ClientSession,
    ) -> str | None:
        """
        Fetch HTML content from a URL.

        Args:
            url: URL to fetch.
            session: aiohttp ClientSession.

        Returns:
            HTML content if successful, None otherwise.
        """
        try:
            async with session.get(
                url,
                headers={
                    "User-Agent": settings.crawler.user_agent,
                },
                timeout=aiohttp.ClientTimeout(total=settings.crawler.timeout),
                ssl=False,
            ) as response:
                if response.status == 200:
                    text = await response.text()
                    logger.debug(f"Fetched {url} ({len(text)} bytes)")
                    return text

                logger.debug(f"Failed to fetch {url}: status {response.status}")
                return None

        except asyncio.TimeoutError:
            logger.debug(f"Timeout fetching {url}")
            return None
        except aiohttp.ClientError as e:
            logger.debug(f"Client error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.debug(f"Unexpected error fetching {url}: {e}")
            return None

    def extract_links_from_html(self, html: str) -> list[str]:
        """
        Extract all links from HTML content.

        Skips excluded tags like nav, footer, header.

        Args:
            html: HTML content to parse.

        Returns:
            List of absolute URLs.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Remove excluded tags
            for tag_name in self.excluded_tags:
                for element in soup.find_all(tag_name):
                    element.decompose()

            links: list[str] = []
            for link in soup.find_all("a", href=True):
                href_value = link["href"]
                href = href_value.strip() if isinstance(href_value, str) else ""
                if href:
                    links.append(href)

            logger.debug(f"Extracted {len(links)} links from HTML")
            return links

        except Exception as e:
            logger.debug(f"Failed to parse HTML: {e}")
            return []

    def convert_to_absolute_url(self, base_url: str, href: str) -> str:
        """
        Convert relative URL to absolute URL.

        Args:
            base_url: Base URL for relative path resolution.
            href: Relative or absolute URL.

        Returns:
            Absolute URL.
        """
        from urllib.parse import urljoin

        # Skip non-HTTP URLs
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            return ""

        # Return as-is if already absolute
        if href.startswith(("http://", "https://")):
            return href

        # Convert relative to absolute
        return urljoin(base_url, href)

    async def find_domains_from_url(
        self,
        url: str,
        session: aiohttp.ClientSession,
    ) -> list[Domain]:
        """
        Find all .gov.bd domains from a URL.

        This is the main entry point for domain discovery:
        1. Fetch URL content
        2. Extract links
        3. Normalize URLs
        4. Filter for .gov.bd domains
        5. Return domain objects

        Args:
            url: URL to crawl.
            session: aiohttp ClientSession.

        Returns:
            List of Domain objects for found .gov.bd domains.

        Example:
            >>> async with aiohttp.ClientSession() as session:
            ...     domains = await finder.find_domains_from_url("https://bangladesh.gov.bd", session)
        """
        found_domains: list[Domain] = []

        # Fetch URL content
        html = await self.fetch_url_content(url, session)
        if not html:
            return found_domains

        # Extract links
        links = self.extract_links_from_html(html)

        # Process each link
        for href in links:
            # Convert to absolute URL
            absolute_url = self.convert_to_absolute_url(url, href)
            if not absolute_url:
                continue

            # Normalize URL
            normalized = self.normalize_url(absolute_url)

            # Extract domain name
            domain_name = self.normalize_domain(normalized)

            # Check if allowed TLD
            if not self.is_allowed_domain(domain_name):
                continue

            # Skip if already found (simple dedup)
            if any(d.domain == domain_name for d in found_domains):
                continue

            # Create Domain object
            domain_obj = Domain(
                domain=domain_name,
                protocol="https" if absolute_url.startswith("https://") else "http",
                is_live=True,  # Assume live until verified
            )
            found_domains.append(domain_obj)
            logger.debug(f"Found domain: {domain_name}")

        return found_domains

    async def find_domain_from_url(self, url: str) -> Domain | None:
        """
        Extract a domain directly from a URL.

        Args:
            url: URL to extract domain from.

        Returns:
            Domain object if URL is for allowed TLD, None otherwise.
        """
        domain = self.normalize_domain(url)

        if self.is_allowed_domain(domain):
            protocol = "https" if url.startswith("https://") else "http"
            return Domain(
                domain=domain,
                protocol=protocol,
                is_live=True,
            )

        return None


# Convenience function for quick domain extraction
async def extract_domains(
    url: str,
    session: aiohttp.ClientSession,
) -> list[Domain]:
    """
    Extract domains from a URL.

    Convenience wrapper for DomainFinder.find_domains_from_url().

    Args:
        url: URL to crawl.
        session: aiohttp ClientSession.

    Returns:
        List of found domains.
    """
    finder = DomainFinder()
    return await finder.find_domains_from_url(url, session)
