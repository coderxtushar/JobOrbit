"""Resume parsing: PDF, DOCX, empty and malformed inputs."""

from __future__ import annotations

import pytest

from app.services.resume_parser import (
    ResumeExtractionError,
    parse_resume_bytes,
    parse_resume_text,
    split_sections,
)
from app.services.storage import CorruptUpload, FileTooLarge, UnsupportedFileType, store_resume
from tests.conftest import SAMPLE_RESUME_LINES, make_docx, make_pdf


def test_docx_parsing_extracts_every_section() -> None:
    _, result = parse_resume_bytes(make_docx(SAMPLE_RESUME_LINES), ".docx")
    fields = result.fields

    assert fields.full_name == "Priya Nair"
    assert fields.email == "priya.nair@example.com"
    assert "98765" in fields.phone
    assert fields.links == ["https://github.com/priyanair"]
    assert {"python", "fastapi", "postgresql", "aws", "docker"} <= set(fields.skills)
    assert len(fields.education) == 1
    assert fields.education[0]["degree"].lower().startswith("b.tech")
    assert fields.education[0]["end_year"] == "2026"
    assert fields.graduation_date == "2026"
    assert [project["name"] for project in fields.projects] == ["Job Matcher"]
    assert fields.certifications == ["AWS Certified Cloud Practitioner"]
    assert fields.achievements == ["First place, college hackathon 2025"]


def test_pdf_parsing_extracts_contact_and_skills() -> None:
    _, result = parse_resume_bytes(make_pdf(SAMPLE_RESUME_LINES), ".pdf")
    assert result.fields.email == "priya.nair@example.com"
    assert "python" in result.fields.skills


def test_education_entries_are_not_merged() -> None:
    """Two education rows must stay separate, so the graduation year is the latest one."""
    lines = [
        "Ravi Kumar",
        "EDUCATION",
        "B.Tech in Information Technology, Anna University, 2021 - 2025, CGPA 8.1",
        "12th CBSE, Delhi Public School, 2021, 91%",
    ]
    _, result = parse_resume_bytes(make_docx(lines), ".docx")
    assert len(result.fields.education) == 2
    assert result.fields.graduation_date == "2025"


def test_empty_resume_reports_a_warning_and_invents_nothing() -> None:
    result = parse_resume_text("")
    assert result.fields.skills == []
    assert result.fields.full_name == ""
    assert result.fields.estimated_years_experience is None
    assert any("no readable text" in warning.lower() for warning in result.warnings)


def test_whitespace_only_resume_is_treated_as_empty() -> None:
    result = parse_resume_text("   \n\n\t  \n ")
    assert result.fields.skills == []
    assert result.warnings


def test_very_short_resume_is_flagged_as_suspicious() -> None:
    result = parse_resume_text("Priya Nair\npriya@example.com\nPython")
    assert any("unusually short" in warning for warning in result.warnings)


def test_resume_without_section_headings_still_infers_skills_but_warns() -> None:
    text = (
        "Ananya Rao is a developer who has worked with Python, Docker and PostgreSQL "
        "on several production services over the last few months while studying."
    )
    result = parse_resume_text(text)
    assert {"python", "docker", "postgresql"} <= set(result.fields.skills)
    assert any("skills" in warning for warning in result.warnings)
    assert result.fields.field_confidence["skills"] == pytest.approx(0.4)


def test_years_experience_is_none_when_unknowable() -> None:
    result = parse_resume_text("\n".join(SAMPLE_RESUME_LINES))
    assert result.fields.estimated_years_experience is None


def test_explicit_years_experience_statement_is_used() -> None:
    result = parse_resume_text(
        "Dev Mehta\nSUMMARY\nBackend engineer with 3 years of professional experience.\n"
        "SKILLS\nPython, Go"
    )
    assert result.fields.estimated_years_experience == 3.0


def test_malformed_pdf_bytes_raise_a_clear_error() -> None:
    with pytest.raises(ResumeExtractionError):
        parse_resume_bytes(b"%PDF-1.4 this is not a real pdf body", ".pdf")


def test_malformed_docx_bytes_raise_a_clear_error() -> None:
    with pytest.raises(ResumeExtractionError):
        parse_resume_bytes(b"PK\x03\x04 not really a docx", ".docx")


def test_unsupported_extension_is_rejected() -> None:
    with pytest.raises(ResumeExtractionError):
        parse_resume_bytes(b"hello", ".txt")


def test_section_splitting_recognises_uppercase_headings() -> None:
    sections = split_sections("\n".join(SAMPLE_RESUME_LINES))
    assert "skills" in sections
    assert "education" in sections
    assert "projects" in sections


# --------------------------------------------------------------------------------------
# Upload validation
# --------------------------------------------------------------------------------------


def test_storage_rejects_an_unsupported_extension(_isolated_settings) -> None:
    with pytest.raises(UnsupportedFileType):
        store_resume("resume.txt", b"hello", _isolated_settings)


def test_storage_rejects_an_empty_file(_isolated_settings) -> None:
    with pytest.raises(CorruptUpload):
        store_resume("resume.pdf", b"", _isolated_settings)


def test_storage_rejects_content_that_contradicts_the_extension(_isolated_settings) -> None:
    """A renamed file must not reach the parser."""
    with pytest.raises(CorruptUpload):
        store_resume("resume.pdf", b"MZ\x90\x00 this is an executable", _isolated_settings)


def test_storage_rejects_an_oversized_file(_isolated_settings) -> None:
    oversized = b"%PDF-" + b"0" * (_isolated_settings.max_upload_bytes + 1)
    with pytest.raises(FileTooLarge):
        store_resume("resume.pdf", oversized, _isolated_settings)


def test_storage_rebuilds_the_filename_and_stays_inside_the_data_directory(
    _isolated_settings,
) -> None:
    stored = store_resume("../../../etc/passwd.pdf", b"%PDF-1.4 ok", _isolated_settings)
    assert ".." not in stored.path.name
    assert stored.path.parent == _isolated_settings.resume_dir.resolve() or (
        stored.path.parent == _isolated_settings.resume_dir
    )
    assert stored.path.is_file()


# --------------------------------------------------------------------------------------
# Regressions found by parsing a real LaTeX-typeset resume
# --------------------------------------------------------------------------------------


def test_hyphenated_line_breaks_are_rejoined_into_whole_skills() -> None:
    """A word split by justification must not become two garbage skills.

    LaTeX wraps "Terminal-Based Work-\nflows", which previously produced the skills
    "terminal-based work" and "flows" — neither of which can ever match a job requirement.
    """
    from app.services.resume_parser import dehyphenate, parse_resume_text

    assert dehyphenate("execu-\ntion") == "execution"
    assert dehyphenate("Work-\nflows") == "Workflows"
    assert dehyphenate("Full-\nStack") == "Full-\nStack"

    text = "\n".join(
        [
            "Asha Rao",
            "asha@example.com",
            "TECHNICAL SKILLS",
            "Tools: Docker, Kubernetes, Terminal-Based Work-",
            "flows, Regression Detection.",
            "GenAI: Reinforcement Learning Tra-",
            "jectory Analysis, Evaluation Harnesses.",
        ]
    )
    fields = parse_resume_text(dehyphenate(text)).fields
    assert "flows" not in fields.skills
    assert "jectory analysis" not in fields.skills
    assert "terminal-based workflows" in fields.skills
    assert "reinforcement learning trajectory analysis" in fields.skills


def test_a_pdf_hyperlink_is_read_even_when_the_url_is_not_visible_text() -> None:
    """Resume headers link labels, not URLs; the URLs live in link annotations."""
    import fitz

    from app.services.resume_parser import parse_resume_bytes

    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 60), "Asha Rao\nasha@example.com\nPortfolio GitHub", fontsize=10)
    page.insert_link(
        {
            "kind": fitz.LINK_URI,
            "from": fitz.Rect(50, 70, 120, 85),
            "uri": "https://github.com/asharao",
        }
    )
    data = document.tobytes()
    document.close()

    _text, result = parse_resume_bytes(data, ".pdf")
    assert "https://github.com/asharao" in result.fields.links


def test_an_education_year_on_a_separate_line_is_still_found() -> None:
    """One-column resumes print institution, degree and dates on separate lines."""
    from app.services.resume_parser import parse_resume_text

    text = "\n".join(
        [
            "Asha Rao",
            "asha@example.com",
            "EDUCATION",
            "Invertis University",
            "Bareilly, Uttar Pradesh",
            "Bachelor of Technology in Computer Science Engineering",
            "Aug 2022 - Jun 2026",
        ]
    )
    result = parse_resume_text(text)
    entry = result.fields.education[0]
    assert entry["end_year"] == "2026"
    assert entry["start_year"] == "2022"
    assert entry["institution"] == "Invertis University"
    assert result.fields.graduation_date == "2026"
    assert not any("none carried a year" in warning for warning in result.warnings)


def test_project_bullets_belong_to_their_title_not_to_themselves() -> None:
    """A wrapped bullet must not become a project whose name is a sentence fragment."""
    from app.services.resume_parser import parse_resume_text

    text = "\n".join(
        [
            "Asha Rao",
            "asha@example.com",
            "PROJECTS",
            "BrandBot AI Agent",
            "Python, FastAPI, Langchain, React.js, Tailwind CSS",
            "\u2022 Built an autonomous agent using LangChain and Gemini that automates",
            "brand analysis, trend research and content creation.",
            "Snap UI",
            "Next.js, React.js, Typescript, Tailwind CSS",
            "\u2022 Developed an AI-driven UI builder for modern web",
            "interfaces effortlessly.",
        ]
    )
    projects = parse_resume_text(text).fields.projects
    assert [project["name"] for project in projects] == ["BrandBot AI Agent", "Snap UI"]
    assert "LangChain" in projects[0]["description"]
    assert "python" in projects[0]["technologies"]
    assert "next.js" in projects[1]["technologies"]


def test_a_comma_separated_stack_is_detected_despite_punctuation() -> None:
    """'Python, FastAPI' must match; the old space-padded test missed every comma case."""
    from app.services.resume_parser import parse_resume_text

    text = "\n".join(
        [
            "Asha Rao",
            "asha@example.com",
            "PROJECTS",
            "Job Matcher",
            "Python, FastAPI, PostgreSQL, Docker",
            "\u2022 Ranks jobs for a candidate.",
        ]
    )
    technologies = parse_resume_text(text).fields.projects[0]["technologies"]
    assert {"python", "fastapi", "postgresql", "docker"} <= set(technologies)


def test_hyperlinks_do_not_leak_into_the_skill_list() -> None:
    """Link URLs must never become skills.

    The skills section is often the last block on the page, so an earlier fix that appended
    link URLs to the extracted text had them absorbed into that section, turning
    "github.com", "in" and "u" into skills that then matched job requirements.
    """
    import fitz

    from app.services.resume_parser import parse_resume_bytes

    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (40, 60),
        "\n".join(
            [
                "Asha Rao",
                "asha@example.com",
                "TECHNICAL SKILLS",
                "Languages: Python, JavaScript",
            ]
        ),
        fontsize=9,
    )
    page.insert_link(
        {
            "kind": fitz.LINK_URI,
            "from": fitz.Rect(40, 50, 110, 62),
            "uri": "https://github.com/asharao",
        }
    )
    data = document.tobytes()
    document.close()

    fields = parse_resume_bytes(data, ".pdf")[1].fields
    assert "https://github.com/asharao" in fields.links
    for skill in fields.skills:
        assert "github.com" not in skill
        assert skill not in {"in", "u", "com"}
    assert {"python", "javascript"} <= set(fields.skills)
