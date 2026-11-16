"""Parse bounded, text-based DOCX question blocks without executing document content."""

import io
import re
import zipfile
from xml.etree import ElementTree

from .questions import normalize_question

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def parse_word_choices(content):
    from .errors import TemplateValidationError
    from .questions import invalid

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(e.file_size for e in entries) > 50 * 1024 * 1024:
                invalid("file", "docx_expanded_size_limit")
            if any("vbaproject" in e.filename.lower() for e in entries):
                invalid("file", "docx_macros_not_allowed")
            xml = archive.read("word/document.xml")
            if len(xml) > 10 * 1024 * 1024 or b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                invalid("file", "unsafe_docx")
            root = ElementTree.fromstring(xml)
    except (KeyError, ValueError, OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise TemplateValidationError(detail={"file": "invalid_docx"}) from exc
    lines = [
        "".join(t.text or "" for t in p.findall(".//w:t", NS)).strip()
        for p in root.findall(".//w:p", NS)
    ]
    rows, errors = [], []
    block = None

    def finish():
        if block is None:
            return
        try:
            answers = re.findall(r"[A-F]", block.get("answers", "").upper())
            if not answers:
                invalid("answer", "答案不能为空")
            kind = block.get("kind") or ("MULTIPLE_CHOICE" if len(answers) > 1 else "SINGLE_CHOICE")
            public, private, score = normalize_question(
                task_type=kind,
                public={"options": block["options"]},
                max_score=block.get("score", "5"),
                marking={
                    "correct_option_ids": answers,
                    "explanation": block.get("explanation", ""),
                },
            )
            rows.append({
                "title": block["stem"][:160],
                "description": block["stem"],
                "task_type": kind,
                "question_spec": public,
                "marking_spec": private,
                "max_score": str(score),
            })
        except (TemplateValidationError, ValueError, ArithmeticError) as exc:
            errors.append({"row": block["line"], "error": getattr(exc, "detail", str(exc))})

    for index, line in enumerate(lines, 1):
        if not line:
            continue
        start = re.match(r"^(?:第\s*)?\d+\s*[.、．)）]\s*(.+)$", line)
        if start:
            finish()
            stem = start.group(1)
            kind = (
                "MULTIPLE_CHOICE"
                if "多选" in stem[:8]
                else "SINGLE_CHOICE"
                if "单选" in stem[:8]
                else None
            )
            stem = re.sub(r"^[【\[（(]?(?:单选题?|多选题?)[】\]）)]?\s*", "", stem)
            block = {"stem": stem, "options": [], "line": index, "kind": kind}
        elif block is not None:
            option = re.match(r"^([A-Fa-f])\s*[.、．:：)）]\s*(.+)$", line)
            field = re.match(r"^(正确答案|答案|参考答案|解析|分值|题型)\s*[:：]\s*(.*)$", line)
            if option:
                block["options"].append({"id": option.group(1).upper(), "text": option.group(2)})
            elif field:
                key, value = field.groups()
                if "答案" in key:
                    block["answers"] = value
                elif key == "解析":
                    block["explanation"] = value
                elif key == "分值":
                    block["score"] = value.removesuffix("分").strip()
                else:
                    block["kind"] = "MULTIPLE_CHOICE" if "多选" in value else "SINGLE_CHOICE"
            elif not block["options"]:
                block["stem"] += "\n" + line
            else:
                errors.append({
                    "row": index,
                    "error": "无法识别段落，请按题号、选项、答案、解析格式填写",
                })
        elif not line.startswith(("选择题", "试题", "题目")):
            errors.append({"row": index, "error": "题目必须以题号开始，例如 1. 题干"})
    finish()
    if not rows and not errors:
        invalid("file", "questions_required")
    if len(rows) + len(errors) > 5000:
        invalid("file", "question_count_limit")
    return rows, errors
