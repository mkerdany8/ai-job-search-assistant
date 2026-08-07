"""Web search tool backed by Tavily."""

import logging
import os

from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

log = logging.getLogger(__name__)

# Tool schema handed to the LLM so it can decide when to search.
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current information about a company, role, or "
            "technology. Use this to research employers, recent news, company "
            "size, culture, or anything not present in the source document."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query. Be specific.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class SearchUnavailable(Exception):
    """Raised when search cannot run at all, for example a missing API key."""


def web_search(query: str, max_results: int = 5) -> str:
    """Run a search and return results as plain text for the LLM.

    Never raises on network or API failure. Returns an explanatory string
    instead, so a failed search degrades the research rather than killing
    the run.
    """
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise SearchUnavailable("TAVILY_API_KEY is not set")

    log.debug("Tool call: web_search(%r)", query)
    try:
        client = TavilyClient(api_key=key)
        resp = client.search(query=query, max_results=max_results)
    except Exception as e:
        log.debug("Search failed: %s", e)
        return f"Search failed for {query!r}: {e}. No results available."

    results = resp.get("results", [])
    if not results:
        log.debug("Search returned 0 results")
        return f"No results found for {query!r}."

    log.debug(
        "Search returned %d results, top: %s",
        len(results),
        results[0].get("url", "?"),
    )

    lines = []
    for r in results:
        lines.append(f"[{r.get('title', 'untitled')}] ({r.get('url', '')})")
        lines.append(r.get("content", "").strip())
        lines.append("")
    return "\n".join(lines)
