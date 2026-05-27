"""Adapter for semantic document blocks returned by dots.ocr."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any


DEFAULT_DOTSOCR_BASE_URL = "https://api.duckduck.cloud/v1"
DEFAULT_DOTSOCR_MODEL = "iairlab/dots.ocr-1.5"
DOTSOCR_ORDERING_PROMPT = """Extract the document layout and text in reading order.
Return JSON only: an array of semantic blocks in the order in which they should be read.
Each text-bearing block must contain fields "bbox", "category", and "text".
Keep natural semantic grouping such as titles and paragraphs.
Use pixel coordinates with a top-left origin.
Bbox format: [x1, y1, x2, y2].
You may include non-text regions, but text blocks must stay in reading order."""


def extract_dotsocr_blocks(
    image_path: str | Path,
    *,
    client: Any | None = None,
    api_key: str | None = None,
    base_url: str = DEFAULT_DOTSOCR_BASE_URL,
    model: str = DEFAULT_DOTSOCR_MODEL,
    prompt: str = DOTSOCR_ORDERING_PROMPT,
    page_number: int = 1,
    raw_response_path: str | Path | None = None,
    timeout: float = 180.0,
    max_retries: int = 1,
) -> list[dict[str, Any]]:
    """Request semantic blocks, preserving the ordering returned by dots.ocr."""
    image_path = Path(image_path)
    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError('Install dots.ocr dependencies with: uv pip install -e ".[dotsocr]"') from exc
        token = api_key or os.environ.get("LITELLM_API_KEY")
        if not token:
            raise RuntimeError("Set LITELLM_API_KEY before running dots.ocr evaluation.")
        client = OpenAI(api_key=token, base_url=base_url, timeout=timeout, max_retries=max_retries)

    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    mime_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
                ],
            }
        ],
        temperature=0,
    )
    content = response.choices[0].message.content or ""
    if raw_response_path:
        raw_path = Path(raw_response_path)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(content, encoding="utf-8")
    return parse_dotsocr_blocks_response(content, page_number=page_number)


def parse_dotsocr_blocks_response(content: str, page_number: int = 1) -> list[dict[str, Any]]:
    """Parse JSON semantic blocks or ordered plain-text/Markdown model output."""
    try:
        payload = _extract_json_payload(content)
    except (ValueError, json.JSONDecodeError):
        return _parse_ordered_text_blocks(content, page_number=page_number)
    if isinstance(payload, dict):
        payload = payload.get("elements") or payload.get("blocks") or payload.get("results") or []
    if not isinstance(payload, list):
        return _parse_ordered_text_blocks(content, page_number=page_number)

    blocks: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        block = {
            "id": f"dotsocr_block_{len(blocks)}",
            "category": str(item.get("category", "Text")),
            "text": str(item["text"]).strip(),
            "page_number": page_number,
            "response_format": "json",
        }
        bbox = item.get("bbox")
        if bbox is not None:
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise ValueError("dots.ocr text block bbox must use [x1, y1, x2, y2] format")
            x1, y1, x2, y2 = [float(value) for value in bbox]
            if x2 < x1 or y2 < y1:
                raise ValueError("dots.ocr bbox must satisfy x2 >= x1 and y2 >= y1")
            block["bbox"] = {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}
        blocks.append(block)
    return blocks


def _extract_json_payload(content: str) -> Any:
    stripped = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.IGNORECASE | re.DOTALL)
    if fenced:
        stripped = fenced.group(1)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = min((index for index in (stripped.find("["), stripped.find("{")) if index >= 0), default=-1)
        if start < 0:
            raise ValueError("dots.ocr response does not contain JSON") from None
        end = max(stripped.rfind("]"), stripped.rfind("}"))
        if end < start:
            raise ValueError("dots.ocr response contains incomplete JSON") from None
        return json.loads(stripped[start : end + 1])


def _parse_ordered_text_blocks(content: str, page_number: int) -> list[dict[str, Any]]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", content.strip()) if chunk.strip()]
    blocks: list[dict[str, Any]] = []
    for chunk in chunks:
        category = "Heading" if re.match(r"^#{1,6}\s+", chunk) else "Text"
        blocks.append(
            {
                "id": f"dotsocr_block_{len(blocks)}",
                "category": category,
                "text": chunk,
                "page_number": page_number,
                "response_format": "ordered_text",
            }
        )
    return blocks
