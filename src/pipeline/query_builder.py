from __future__ import annotations

from typing import Any


# TwitterAPI.io rejects the final query above 512 characters. The adapter adds
# a 44-character since/until window, so keep generated query bodies below this
# limit before the window is attached.
MAX_BASE_QUERY_LENGTH = 460


def build_x_search_queries(keyword_config: dict[str, Any], brand_key: str) -> list[str]:
    brand = keyword_config["brands"][brand_key]
    terms = brand.get("brand_terms", [])
    negative_terms = brand.get("query_negative_terms", [])
    negative_clause = _negative_clause(negative_terms)
    query_groups = brand.get("query_groups", [])

    if query_groups:
        queries = []
        for group in query_groups:
            group_terms = group.get("terms", []) if isinstance(group, dict) else []
            group_context = group.get("context_terms", []) if isinstance(group, dict) else []
            if group_terms:
                queries.extend(_bounded_group_queries(group_terms, group_context, negative_clause))
        if queries:
            return queries

    if brand_key == "joybuy":
        primary_terms = [
            term
            for term in terms
            if term.lower() not in {"jd", "京东", "jingdong"}
        ]
        queries = _bounded_group_queries(primary_terms, [], negative_clause)
        jd_terms = [
            "JD.com",
            "Jingdong",
            "京东",
            "JD shopping",
            "JD ecommerce",
            "JD order",
            "JD tracking",
            "JD parcel",
            "JD customer service",
            "JD seller",
            "JD warehouse",
            "JD overseas",
            "JD Europe",
            "JD UK",
            "JD Germany",
            "JD France",
            "JD Netherlands",
            "JD Belgium",
            "JD Luxembourg",
        ]
        queries.extend(_bounded_group_queries(jd_terms, [], negative_clause))
        return queries

    context_terms = brand.get("query_context_terms", [])
    return _bounded_group_queries(terms, context_terms, negative_clause)


def _bounded_group_queries(
    terms: list[str],
    context_terms: list[str],
    negative_clause: str,
    max_length: int = MAX_BASE_QUERY_LENGTH,
) -> list[str]:
    query = _render_group_query(terms, context_terms, negative_clause)
    if len(query) <= max_length:
        return [query]

    splittable: list[tuple[str, int]] = []
    if len(terms) > 1:
        splittable.append(("terms", len(_or_clause(terms))))
    if len(context_terms) > 1:
        splittable.append(("context", len(_or_clause(context_terms))))
    if not splittable:
        raise ValueError(f"Search query cannot fit provider limit ({len(query)} > {max_length})")

    dimension = max(splittable, key=lambda item: item[1])[0]
    values = terms if dimension == "terms" else context_terms
    midpoint = max(1, len(values) // 2)
    halves = (values[:midpoint], values[midpoint:])
    bounded: list[str] = []
    for half in halves:
        next_terms = half if dimension == "terms" else terms
        next_context = half if dimension == "context" else context_terms
        bounded.extend(_bounded_group_queries(next_terms, next_context, negative_clause, max_length))
    return list(dict.fromkeys(bounded))


def _render_group_query(terms: list[str], context_terms: list[str], negative_clause: str) -> str:
    context_clause = f" ({_or_clause(context_terms)})" if context_terms else ""
    return f"({_or_clause(terms)}){context_clause} -filter:retweets {negative_clause}".strip()


def _or_clause(terms: list[str]) -> str:
    return " OR ".join(_format_term(term) for term in terms if term.strip())


def _format_term(term: str) -> str:
    normalized = term.strip()
    if " " in normalized or "." in normalized:
        return f'"{normalized}"'
    return normalized


def _negative_clause(terms: list[str]) -> str:
    if not terms:
        return ""
    return " ".join(f"-{_format_term(term)}" for term in terms if term.strip())
