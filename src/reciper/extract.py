"""Deterministic extraction of recipe candidates from webpage HTML."""

from __future__ import annotations

import html as html_module
import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from reciper.errors import ExtractionError
from reciper.fetch import FetchedPage
from reciper.models import ExtractedRecipe

MAX_ARTICLE_CHARS = 30_000
MAX_TIP_CHARS = 12_000
MAX_CORE_CHARS = 60_000
MAX_CORE_LINE_CHARS = 4_000
MAX_INGREDIENTS = 250
MAX_INSTRUCTIONS = 300
MAX_NOTES = 150
MAX_JSON_DEPTH = 30
_YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_PATH_PREFIXES = {"embed", "live", "shorts", "v"}
_YOUTUBE_URL_ATTRIBUTES = (
    "href",
    "src",
    "data-src",
    "data-lazy-src",
    "data-url",
    "data-video-url",
    "data-embed-url",
    "content",
)
_ISO_DURATION = re.compile(
    r"^P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$",
    flags=re.IGNORECASE,
)
TIP_HEADING_PATTERNS = (
    r"\btips?\b",
    r"\bnotes?\b",
    r"\bsuccess\b",
    r"\bsubstitutions?\b",
    r"\bvariations?\b",
    r"\bmake[ -]ahead\b",
    r"\bstorage\b",
    r"\bfreez(?:e|ing)\b",
    r"\btroubleshoot(?:ing)?\b",
)
CARD_SELECTORS = (
    ".wprm-recipe-container",
    ".tasty-recipes",
    ".mv-create-card",
    "[class*='recipe-card']",
    "[class*='recipe_card']",
)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    raw = html_module.unescape(str(value))
    if "<" in raw and ">" in raw:
        raw = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", raw).strip()


def _clean_list(values: Iterable[object]) -> list[str]:
    """Clean source lines without removing legitimate repeated entries."""

    return [text for text in (_clean_text(value) for value in values) if text]


def _schema_types(node: dict[str, Any]) -> set[str]:
    raw_types = node.get("@type", [])
    if isinstance(raw_types, str):
        raw_types = [raw_types]
    return {str(value).rstrip("/").rsplit("/", 1)[-1].lower() for value in raw_types}


def _walk_json(value: object) -> Iterable[dict[str, Any]]:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def _json_ld_nodes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            document = json.loads(raw)
        except (json.JSONDecodeError, RecursionError, TypeError):
            continue
        nodes.extend(_walk_json(document))
    return nodes


def _normalize_youtube_url(value: object) -> str | None:
    raw = html_module.unescape(str(value)).strip()
    if not raw or "youtu" not in raw.casefold():
        return None
    if raw.startswith("//"):
        raw = f"https:{raw}"
    elif not re.match(r"^[a-z][a-z0-9+.-]*://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = (parsed.hostname or "").casefold().rstrip(".")
    parts = [part for part in parsed.path.split("/") if part]
    video_id: str | None = None

    if host == "youtu.be" or host.endswith(".youtu.be"):
        video_id = parts[0] if parts else None
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path.rstrip("/").casefold() == "/watch":
            video_id = next(iter(parse_qs(parsed.query).get("v", [])), None)
        elif len(parts) >= 2 and parts[0].casefold() in _YOUTUBE_PATH_PREFIXES:
            video_id = parts[1]
    elif (
        host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com")
    ) and len(parts) >= 2 and parts[0].casefold() == "embed":
        video_id = parts[1]

    if not video_id or not _YOUTUBE_VIDEO_ID.fullmatch(video_id):
        return None
    return f"https://www.youtube.com/watch?v={video_id}"


def _youtube_url_from_value(value: object, *, depth: int = 0) -> str | None:
    if depth > MAX_JSON_DEPTH:
        return None
    if isinstance(value, str):
        return _normalize_youtube_url(value)
    if isinstance(value, list):
        for item in value:
            if url := _youtube_url_from_value(item, depth=depth + 1):
                return url
        return None
    if not isinstance(value, dict):
        return None

    priority_keys = ("contentUrl", "embedUrl", "url")
    for key in priority_keys:
        if key in value and (url := _youtube_url_from_value(value[key], depth=depth + 1)):
            return url
    for key, item in value.items():
        if key not in priority_keys and (
            url := _youtube_url_from_value(item, depth=depth + 1)
        ):
            return url
    return None


def _extract_youtube_url(
    soup: BeautifulSoup,
    *,
    json_nodes: list[dict[str, Any]],
    selected_recipe: dict[str, Any] | None,
) -> str | None:
    if selected_recipe and (url := _youtube_url_from_value(selected_recipe.get("video"))):
        return url

    for node in json_nodes:
        node_types = _schema_types(node)
        if "recipe" in node_types:
            candidate = node.get("video")
        elif "videoobject" in node_types:
            candidate = node
        else:
            continue
        if url := _youtube_url_from_value(candidate):
            return url

    for element in soup.find_all(True):
        for attribute in _YOUTUBE_URL_ATTRIBUTES:
            value = element.get(attribute)
            if value and (url := _normalize_youtube_url(value)):
                return url
    return None


def _flatten_instruction_value(
    value: object,
    *,
    section: str | None = None,
    depth: int = 0,
) -> list[str]:
    if depth > MAX_JSON_DEPTH:
        return []
    if isinstance(value, str):
        if "<li" in value.lower():
            list_items = BeautifulSoup(value, "html.parser").find_all("li")
            if list_items:
                return _clean_list(item.get_text(" ", strip=True) for item in list_items)
        text = _clean_text(value)
        return [f"{section}: {text}" if section and text else text] if text else []

    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(_flatten_instruction_value(item, section=section, depth=depth + 1))
        return lines

    if not isinstance(value, dict):
        return []

    types = _schema_types(value)
    name = _clean_text(value.get("name"))
    items = value.get("itemListElement") or value.get("steps")
    if "howtosection" in types or (items is not None and not value.get("text")):
        return _flatten_instruction_value(items, section=name or section, depth=depth + 1)

    text = _clean_text(value.get("text") or value.get("description") or name)
    if text:
        if section and not text.casefold().startswith(section.casefold()):
            text = f"{section}: {text}"
        return [text]
    return _flatten_instruction_value(items, section=section, depth=depth + 1)


def _flatten_strings(value: object, *, depth: int = 0) -> list[str]:
    if value is None or depth > MAX_JSON_DEPTH:
        return []
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            lines.extend(_flatten_strings(item, depth=depth + 1))
        return lines
    if isinstance(value, dict):
        text = value.get("text") or value.get("description") or value.get("name")
        return [_clean_text(text)] if _clean_text(text) else []
    text = _clean_text(value)
    return [text] if text else []


def _first_text(value: object) -> str | None:
    values = _flatten_strings(value)
    return values[0] if values else None


def _readable_duration(value: str) -> str:
    match = _ISO_DURATION.fullmatch(value.strip())
    if not match or not any(match.groupdict().values()):
        return value
    parts: list[str] = []
    for field, label in (
        ("weeks", "week"),
        ("days", "day"),
        ("hours", "hour"),
        ("minutes", "minute"),
        ("seconds", "second"),
    ):
        raw_amount = match.group(field)
        if raw_amount is None:
            continue
        amount = int(raw_amount)
        parts.append(f"{amount} {label}{'' if amount == 1 else 's'}")
    return " ".join(parts) or value


def _recipe_score(recipe: dict[str, Any]) -> int:
    ingredients = _flatten_strings(recipe.get("recipeIngredient") or recipe.get("ingredients"))
    instructions = _flatten_instruction_value(recipe.get("recipeInstructions"))
    return len(ingredients) * 3 + len(instructions) * 4 + int(bool(recipe.get("name")))


def _from_json_ld(recipe: dict[str, Any], source_url: str) -> ExtractedRecipe:
    notes: list[str] = []
    for key in ("recipeNotes", "notes", "tips", "tip"):
        notes.extend(_flatten_strings(recipe.get(key)))

    timing: dict[str, str] = {}
    for output_name, schema_name in (
        ("prep_time", "prepTime"),
        ("cook_time", "cookTime"),
        ("total_time", "totalTime"),
    ):
        value = _first_text(recipe.get(schema_name))
        if value:
            timing[output_name] = _readable_duration(value)

    return ExtractedRecipe(
        source_url=source_url,
        page_title=_first_text(recipe.get("name")),
        description=_first_text(recipe.get("description")),
        yield_text=_first_text(recipe.get("recipeYield")),
        timing=timing,
        ingredient_lines=_clean_list(
            _flatten_strings(recipe.get("recipeIngredient") or recipe.get("ingredients"))
        ),
        instruction_lines=_clean_list(_flatten_instruction_value(recipe.get("recipeInstructions"))),
        note_lines=_clean_list(notes),
    )


def _has_property(element: Tag, property_names: set[str]) -> bool:
    return bool(set(element.get("itemprop", "").split()).intersection(property_names))


def _inside_nested_scope(element: Tag, recipe_scope: Tag) -> bool:
    for parent in element.parents:
        if parent is recipe_scope:
            return False
        if isinstance(parent, Tag) and (
            parent.has_attr("itemscope") or parent.has_attr("itemtype")
        ):
            return True
    return False


def _element_text(element: Tag) -> str:
    raw = element.get("content") or element.get("datetime") or element.get_text(" ", strip=True)
    return _clean_text(raw)


def _property_values(
    scope: Tag,
    property_names: set[str],
    *,
    exclude_nested_scopes: bool = False,
) -> list[str]:
    values: list[str] = []
    for element in scope.select("[itemprop]"):
        if not _has_property(element, property_names):
            continue
        if exclude_nested_scopes and _inside_nested_scope(element, scope):
            continue
        text = _element_text(element)
        if text:
            values.append(text)
    return values


def _microdata_instruction_values(scope: Tag) -> list[str]:
    roots = [
        element
        for element in scope.select("[itemprop]")
        if _has_property(element, {"recipeInstructions"})
    ]
    top_level_roots = [
        element
        for element in roots
        if not any(
            isinstance(parent, Tag) and _has_property(parent, {"recipeInstructions"})
            for parent in element.parents
            if parent is not scope
        )
    ]

    instructions: list[str] = []
    for root in top_level_roots:
        leaf_texts = [
            element
            for element in root.select("[itemprop]")
            if _has_property(element, {"text"}) and not element.select("[itemprop~='text']")
        ]
        if leaf_texts:
            instructions.extend(_element_text(element) for element in leaf_texts)
            continue

        list_items = root.find_all("li")
        if list_items:
            instructions.extend(_element_text(element) for element in list_items)
            continue

        text = _element_text(root)
        if text:
            instructions.append(text)
    return [instruction for instruction in instructions if instruction]


def _from_microdata(soup: BeautifulSoup, source_url: str) -> ExtractedRecipe | None:
    scopes = [
        tag
        for tag in soup.select("[itemtype]")
        if "recipe" in tag.get("itemtype", "").rstrip("/").rsplit("/", 1)[-1].casefold()
    ]
    candidates: list[ExtractedRecipe] = []
    for scope in scopes:
        names = _property_values(scope, {"name", "headline"}, exclude_nested_scopes=True)
        descriptions = _property_values(scope, {"description"}, exclude_nested_scopes=True)
        yields = _property_values(scope, {"recipeYield"}, exclude_nested_scopes=True)
        ingredients = _property_values(
            scope,
            {"recipeIngredient", "ingredients"},
            exclude_nested_scopes=True,
        )
        instructions = _microdata_instruction_values(scope)
        notes = _property_values(scope, {"recipeNotes", "notes"}, exclude_nested_scopes=True)
        timing: dict[str, str] = {}
        for output_name, property_name in (
            ("prep_time", "prepTime"),
            ("cook_time", "cookTime"),
            ("total_time", "totalTime"),
        ):
            values = _property_values(scope, {property_name}, exclude_nested_scopes=True)
            if values:
                timing[output_name] = _readable_duration(values[0])
        candidates.append(
            ExtractedRecipe(
                source_url=source_url,
                page_title=names[0] if names else None,
                description=descriptions[0] if descriptions else None,
                yield_text=yields[0] if yields else None,
                timing=timing,
                ingredient_lines=ingredients,
                instruction_lines=instructions,
                note_lines=notes,
            )
        )
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: len(item.ingredient_lines) + len(item.instruction_lines),
    )


def _card_lines(card: Tag, kind: str) -> list[str]:
    list_selectors = (
        f"[class*='{kind}'] li",
        f"li[class*='{kind}']",
    )
    elements = _unique_elements(
        element for selector in list_selectors for element in card.select(selector)
    )
    if not elements:
        elements = _unique_elements(card.select(f"[class*='{kind}'] p"))
    return _clean_list(element.get_text(" ", strip=True) for element in elements)


def _unique_elements(elements: Iterable[Tag]) -> list[Tag]:
    unique: list[Tag] = []
    seen: set[int] = set()
    for element in elements:
        identity = id(element)
        if identity not in seen:
            seen.add(identity)
            unique.append(element)
    return unique


def _from_known_card(soup: BeautifulSoup, source_url: str) -> ExtractedRecipe | None:
    candidates: list[ExtractedRecipe] = []
    for selector in CARD_SELECTORS:
        for card in soup.select(selector):
            title_tag = card.select_one("h1, h2, h3, [class*='name'], [class*='title']")
            candidates.append(
                ExtractedRecipe(
                    source_url=source_url,
                    page_title=(
                        _clean_text(title_tag.get_text(" ", strip=True)) if title_tag else None
                    ),
                    ingredient_lines=_card_lines(card, "ingredient"),
                    instruction_lines=_card_lines(card, "instruction"),
                    note_lines=_card_lines(card, "note"),
                )
            )
    useful = [
        candidate
        for candidate in candidates
        if candidate.ingredient_lines or candidate.instruction_lines or candidate.note_lines
    ]
    if not useful:
        return None
    return max(
        useful,
        key=lambda item: (
            len(item.ingredient_lines) + len(item.instruction_lines) + len(item.note_lines)
        ),
    )


def _merge_candidates(
    primary: ExtractedRecipe,
    supplements: Iterable[ExtractedRecipe | None],
) -> ExtractedRecipe:
    page_title = primary.page_title
    description = primary.description
    yield_text = primary.yield_text
    timing = dict(primary.timing)
    ingredients = list(primary.ingredient_lines)
    instructions = list(primary.instruction_lines)
    notes = list(primary.note_lines)

    for supplement in supplements:
        if supplement is None:
            continue
        page_title = page_title or supplement.page_title
        description = description or supplement.description
        yield_text = yield_text or supplement.yield_text
        for name, value in supplement.timing.items():
            timing.setdefault(name, value)
        if not ingredients:
            ingredients = list(supplement.ingredient_lines)
        if not instructions:
            instructions = list(supplement.instruction_lines)
        notes.extend(note for note in supplement.note_lines if note not in notes)

    return primary.model_copy(
        update={
            "page_title": page_title,
            "description": description,
            "yield_text": yield_text,
            "timing": timing,
            "ingredient_lines": ingredients,
            "instruction_lines": instructions,
            "note_lines": notes,
        }
    )


def _content_container(soup: BeautifulSoup) -> Tag:
    return soup.find("article") or soup.find("main") or soup.body or soup


def _extract_article_text(container: Tag) -> str:
    cleaned = BeautifulSoup(str(container), "html.parser")
    for unwanted in cleaned.select(
        "script, style, noscript, svg, nav, footer, header, form, aside, iframe, button"
    ):
        unwanted.decompose()

    lines: list[str] = []
    for element in cleaned.select("h1, h2, h3, h4, h5, h6, p, li"):
        text = _clean_text(element.get_text(" ", strip=True))
        if not text or (lines and lines[-1] == text):
            continue
        lines.append(text[:2_000])

    result = "\n".join(lines)
    if len(result) > MAX_ARTICLE_CHARS:
        result = result[:MAX_ARTICLE_CHARS].rsplit("\n", 1)[0] + "\n[article text truncated]"
    return result


def _extract_tip_sections(container: Tag) -> list[str]:
    sections: list[str] = []
    used_chars = 0
    for heading in container.select("h2, h3, h4, h5, h6"):
        heading_text = _clean_text(heading.get_text(" ", strip=True))
        if not any(
            re.search(pattern, heading_text, flags=re.IGNORECASE)
            for pattern in TIP_HEADING_PATTERNS
        ):
            continue

        heading_level = int(heading.name[1])
        lines = [heading_text]
        for sibling in heading.next_siblings:
            if (
                isinstance(sibling, Tag)
                and re.fullmatch(r"h[1-6]", sibling.name or "")
                and int(sibling.name[1]) <= heading_level
            ):
                break
            if not isinstance(sibling, Tag):
                continue
            candidates = [sibling] if sibling.name in {"p", "li"} else sibling.select("p, li")
            lines.extend(
                text
                for text in (_clean_text(item.get_text(" ", strip=True)) for item in candidates)
                if text and text not in lines
            )

        section = "\n".join(lines)
        if len(section) <= len(heading_text):
            continue
        remaining = MAX_TIP_CHARS - used_chars
        if remaining <= 0:
            break
        section = section[:remaining]
        sections.append(section)
        used_chars += len(section)
    return sections


def _section_lines(container: Tag, heading_pattern: str) -> list[str]:
    lines: list[str] = []
    for heading in container.select("h1, h2, h3, h4, h5, h6"):
        heading_text = _clean_text(heading.get_text(" ", strip=True))
        if not re.search(heading_pattern, heading_text, flags=re.IGNORECASE):
            continue
        heading_level = int(heading.name[1])
        for sibling in heading.next_siblings:
            if (
                isinstance(sibling, Tag)
                and re.fullmatch(r"h[1-6]", sibling.name or "")
                and int(sibling.name[1]) <= heading_level
            ):
                break
            if not isinstance(sibling, Tag):
                continue
            if sibling.name in {"li", "p"}:
                elements = [sibling]
            else:
                elements = sibling.select("li") or sibling.select("p")
            lines.extend(_element_text(element) for element in elements)
        if lines:
            break
    return [line for line in lines if line]


def _fallback_section_candidates(container: Tag) -> tuple[list[str], list[str]]:
    ingredients = _section_lines(container, r"\bingredients?\b")
    instructions = _section_lines(
        container,
        r"\b(?:instructions?|directions?|method|preparation)\b",
    )
    quantity_signal = re.compile(
        r"(?:\d|[¼½¾⅓⅔⅛⅜⅝⅞]|\b(?:cups?|tablespoons?|teaspoons?|grams?|"
        r"kilograms?|ounces?|pounds?|milliliters?|liters?|to taste)\b)",
        flags=re.IGNORECASE,
    )
    action_signal = re.compile(
        r"(?:\d|°|\b(?:add|bake|beat|blend|boil|chill|combine|cook|cool|fold|heat|"
        r"knead|mix|preheat|rest|roast|simmer|stir|whisk)\b)",
        flags=re.IGNORECASE,
    )
    if not any(quantity_signal.search(line) for line in ingredients):
        ingredients = []
    if not any(action_signal.search(line) for line in instructions):
        instructions = []
    return ingredients, instructions


def _enforce_source_bounds(source: ExtractedRecipe) -> ExtractedRecipe:
    for label, values, limit in (
        ("ingredients", source.ingredient_lines, MAX_INGREDIENTS),
        ("instructions", source.instruction_lines, MAX_INSTRUCTIONS),
        ("notes", source.note_lines, MAX_NOTES),
    ):
        if len(values) > limit:
            raise ExtractionError(
                f"The webpage contains too many recipe {label} to process safely."
            )
        if any(len(value) > MAX_CORE_LINE_CHARS for value in values):
            raise ExtractionError(f"The webpage contains an unusually large recipe {label} entry.")

    core_values = [
        source.youtube_url or "",
        source.page_title or "",
        source.description or "",
        source.yield_text or "",
        *source.timing.values(),
        *source.ingredient_lines,
        *source.instruction_lines,
        *source.note_lines,
        *source.tip_sections,
    ]
    if sum(len(value) for value in core_values) > MAX_CORE_CHARS:
        raise ExtractionError("The extracted recipe is too large to process safely.")
    return source


class RecipeExtractor:
    """Prefer explicit recipe metadata, retaining article context for tips and fallback."""

    def extract(self, page: FetchedPage) -> ExtractedRecipe:
        soup = BeautifulSoup(page.html, "html.parser")
        container = _content_container(soup)
        article_text = _extract_article_text(container)
        tip_sections = _extract_tip_sections(container)

        json_nodes = _json_ld_nodes(soup)
        json_recipes = [node for node in json_nodes if "recipe" in _schema_types(node)]
        microdata = _from_microdata(soup, page.final_url)
        known_card = _from_known_card(soup, page.final_url)
        selected_recipe = max(json_recipes, key=_recipe_score) if json_recipes else None
        if json_recipes:
            primary = _from_json_ld(selected_recipe, page.final_url)
        else:
            primary = ExtractedRecipe(source_url=page.final_url)
        extracted = _merge_candidates(primary, (microdata, known_card))

        fallback_ingredients, fallback_instructions = _fallback_section_candidates(container)
        extracted = extracted.model_copy(
            update={
                "ingredient_lines": extracted.ingredient_lines or fallback_ingredients,
                "instruction_lines": extracted.instruction_lines or fallback_instructions,
            }
        )

        page_title = extracted.page_title
        if not page_title and soup.title:
            page_title = _clean_text(soup.title.get_text(" ", strip=True))

        extracted = extracted.model_copy(
            update={
                "youtube_url": _extract_youtube_url(
                    soup,
                    json_nodes=json_nodes,
                    selected_recipe=selected_recipe,
                ),
                "page_title": page_title,
                "tip_sections": tip_sections,
                "article_text": article_text,
            }
        )
        if not extracted.ingredient_lines or not extracted.instruction_lines:
            raise ExtractionError("No usable recipe content was found on the webpage.")
        return _enforce_source_bounds(extracted)
