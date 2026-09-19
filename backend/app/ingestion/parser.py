import re
from typing import Any


def parse_document_text(content: str, file_type: str = "txt") -> str:
    if file_type in ("txt", "md"):
        return content
    return content


CLAUSE_PATTERN = re.compile(r"第([一二三四五六七八九十百零]+|\d+)条")
SECTION_PATTERN = re.compile(r"第([一二三四五六七八九十百零]+|\d+)章")


def extract_sections_and_clauses(text: str) -> list[dict[str, Any]]:
    lines = text.split("\n")
    sections: list[dict[str, Any]] = []
    current_section_no: str | None = None
    current_section_title: str | None = None
    section_id_counter = 1
    clauses: list[dict[str, Any]] = []
    current_clause_no: str | None = None
    current_clause_lines: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        sec_match = SECTION_PATTERN.match(line)
        if sec_match:
            if current_clause_no:
                clauses.append({
                    "section_no": current_section_no,
                    "clause_no": current_clause_no,
                    "content": "\n".join(current_clause_lines).strip(),
                })
                current_clause_no = None
                current_clause_lines = []
            current_section_no = sec_match.group(0)
            current_section_title = line[len(sec_match.group(0)):].strip()
            sections.append({
                "local_id": section_id_counter,
                "section_no": current_section_no,
                "title": current_section_title,
            })
            section_id_counter += 1
            continue

        cls_match = CLAUSE_PATTERN.match(line)
        if cls_match:
            if current_clause_no:
                clauses.append({
                    "section_no": current_section_no,
                    "clause_no": current_clause_no,
                    "content": "\n".join(current_clause_lines).strip(),
                })
            current_clause_no = cls_match.group(0)
            current_clause_lines = [line[len(cls_match.group(0)):].strip()]
            continue

        if current_clause_no:
            current_clause_lines.append(line)

    if current_clause_no:
        clauses.append({
            "section_no": current_section_no,
            "clause_no": current_clause_no,
            "content": "\n".join(current_clause_lines).strip(),
        })

    return clauses


CN_NUM_MAP = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100,
}


def normalize_clause_no(clause_no: str) -> int | None:
    digits = re.findall(r"\d+", clause_no)
    if digits:
        return int(digits[0])
    cn_chars = re.findall(r"[一二三四五六七八九十百零]+", clause_no)
    if cn_chars:
        return cn_to_int(cn_chars[0])
    return None


def cn_to_int(s: str) -> int:
    if not s:
        return 0
    if len(s) == 1:
        return CN_NUM_MAP.get(s, 0)
    if s[0] == "十":
        return 10 + (cn_to_int(s[1:]) if len(s) > 1 else 0)
    if "十" in s:
        parts = s.split("十")
        tens = cn_to_int(parts[0]) if parts[0] else 1
        ones = cn_to_int(parts[1]) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    if "百" in s:
        parts = s.split("百")
        hundreds = cn_to_int(parts[0]) if parts[0] else 1
        rest = 0
        if len(parts) > 1 and parts[1]:
            rest = cn_to_int(parts[1])
        return hundreds * 100 + rest
    total = 0
    for c in s:
        total = total * 10 + CN_NUM_MAP.get(c, 0)
    return total
