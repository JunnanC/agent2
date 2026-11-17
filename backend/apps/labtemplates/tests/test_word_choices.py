import io
import zipfile
from xml.sax.saxutils import escape

from django.test import SimpleTestCase

from apps.labtemplates.choice_import import parse_choices


def docx(lines):
    output = io.BytesIO()
    paragraphs = "".join(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in lines)
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            + paragraphs
            + "</w:body></w:document>",
        )
    return output.getvalue()


class WordChoiceTests(SimpleTestCase):
    def test_word_single_and_multiple_choice(self):
        rows, errors = parse_choices(
            docx([
                "1. 单选题 栈的特征？",
                "A. 先进先出",
                "B. 后进先出",
                "答案：B",
                "分值：5",
                "解析：后进先出",
                "2. 多选题 选择编程语言",
                "A. Python",
                "B. Java",
                "C. HTTP",
                "答案：A,B",
                "分值：10",
            ])
        )
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["marking_spec"]["correct_option_ids"], ["B"])
        self.assertEqual(rows[1]["task_type"], "MULTIPLE_CHOICE")
        self.assertEqual(rows[1]["max_score"], "10")

    def test_missing_or_unknown_answer_returns_error_location(self):
        for answer in ["", "答案：F"]:
            rows, errors = parse_choices(docx(["1. 请选择", "A. 甲", "B. 乙", answer]))
            self.assertEqual(rows, [])
            self.assertEqual(errors[0]["row"], 1)
