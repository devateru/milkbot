import os
from pathlib import Path

from docx import Document


def replace_paragraph_text(paragraph, expected, replacement):
    if paragraph.text != expected:
        raise ValueError(f"Expected {expected!r}, found {paragraph.text!r}")

    text_runs = [run for run in paragraph.runs if run.text]
    if not text_runs:
        raise ValueError(f"No text run found for {expected!r}")

    text_runs[0].text = replacement
    for run in text_runs[1:]:
        run.text = ""


source = Path(os.environ["MILKBOT_SOURCE_DOCX"])
output = Path(os.environ["MILKBOT_OUTPUT_DOCX"])

document = Document(str(source))

replacements = {
    "8월 5일 (수)": "8월 5일(수)",
    "나주에서 경주로 출발했습니다. 한국에너지공과대학교에서 광주버스터미널 이동 후 경주로 출발하였습니다.":
        "한국에너지공과대학교에서 광주버스터미널로 이동한 뒤 경주로 출발했습니다.",
    "8월 6일 (목), 8월 7일 (금)": "8월 6일(목), 8월 7일(금)",
    "현장 등록 후 학회에서 제공하는 렉쳐, 포스터 세션, Plenary Talk 등을 수강했습니다.":
        "현장 등록을 마친 뒤 학회에서 진행한 강연과 포스터 세션, Plenary Talk 등에 참석했습니다.",
    "학회 현장등록 영수증": "학회 현장 등록 영수증",
}

seen = set()
for paragraph in document.paragraphs:
    if paragraph.text in replacements:
        original = paragraph.text
        replace_paragraph_text(paragraph, original, replacements[original])
        seen.add(original)

missing = set(replacements) - seen
if missing:
    raise ValueError(f"Missing expected paragraphs: {sorted(missing)}")

output.parent.mkdir(parents=True, exist_ok=True)
document.save(str(output))
print(output)
