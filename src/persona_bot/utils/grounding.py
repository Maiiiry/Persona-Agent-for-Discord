"""検索出典の表示順と件数を統一する。"""

from collections.abc import Iterable, Mapping

from persona_bot.config.constants import MAX_GROUNDING_SOURCES


def normalize_sources(items: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """空の URI を除き、先着順に重複を取り除く。"""
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        raw_uri = item.get("uri")
        uri = raw_uri.strip() if isinstance(raw_uri, str) else ""
        if not uri or uri in seen:
            continue
        raw_title = item.get("title")
        result.append({"uri": uri, "title": raw_title.strip() if isinstance(raw_title, str) else ""})
        seen.add(uri)
        if len(result) >= MAX_GROUNDING_SOURCES:
            break
    return result
