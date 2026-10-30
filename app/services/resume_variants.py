"""Resume variants.

A variant is a *selection and reordering* of facts that already exist in the parsed resume.
The generator has no mechanism to add content: it reads only from ``Resume.extracted_fields``
and the verified profile, and :func:`audit_variant` re-checks the rendered output against
that source so a variant containing an unsourced skill can be detected rather than trusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db.models import CandidateProfile, Resume
from app.services.text import canonical_skill, canonical_skills

JOB_FAMILY_SKILLS: dict[str, tuple[str, ...]] = {
    "backend": (
        "python",
        "java",
        "go",
        "node.js",
        "fastapi",
        "django",
        "flask",
        "express",
        "spring boot",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "rest api",
        "graphql",
        "docker",
        "kubernetes",
        "microservices",
        "sql",
    ),
    "frontend": (
        "javascript",
        "typescript",
        "react",
        "next.js",
        "vue",
        "angular",
        "html",
        "css",
        "tailwind",
        "redux",
        "sass",
        "bootstrap",
        "figma",
    ),
    "fullstack": (
        "javascript",
        "typescript",
        "react",
        "node.js",
        "python",
        "django",
        "fastapi",
        "postgresql",
        "mongodb",
        "rest api",
        "docker",
        "html",
        "css",
        "next.js",
    ),
    "ai_ml": (
        "python",
        "machine learning",
        "deep learning",
        "pytorch",
        "tensorflow",
        "scikit-learn",
        "numpy",
        "pandas",
        "natural language processing",
        "computer vision",
        "mlops",
        "mlflow",
    ),
    "genai": (
        "python",
        "llm",
        "generative ai",
        "langchain",
        "llamaindex",
        "retrieval augmented generation",
        "prompt engineering",
        "transformers",
        "hugging face",
        "embeddings",
        "vector database",
        "agentic ai",
        "openai",
        "fine-tuning",
        "fastapi",
    ),
    "cloud_devops": (
        "aws",
        "azure",
        "google cloud",
        "docker",
        "kubernetes",
        "terraform",
        "ansible",
        "jenkins",
        "github actions",
        "cicd",
        "linux",
        "bash",
        "nginx",
        "prometheus",
        "grafana",
        "serverless",
    ),
    "data": (
        "python",
        "sql",
        "pandas",
        "numpy",
        "airflow",
        "kafka",
        "power bi",
        "tableau",
        "postgresql",
        "excel",
        "elasticsearch",
    ),
    "general_software": (
        "python",
        "java",
        "javascript",
        "c++",
        "sql",
        "git",
        "data structures and algorithms",
        "object oriented programming",
        "testing",
        "system design",
    ),
}

_TITLE_TO_FAMILY: tuple[tuple[tuple[str, ...], str], ...] = (
    (("generative", "genai", "gen ai", "llm", "agentic", "prompt"), "genai"),
    (
        ("machine learning", "ml engineer", "data scientist", "deep learning", "ai engineer"),
        "ai_ml",
    ),
    (
        ("devops", "sre", "site reliability", "platform engineer", "cloud", "infrastructure"),
        "cloud_devops",
    ),
    (("data engineer", "data analyst", "analytics", "business intelligence"), "data"),
    (("full stack", "full-stack", "fullstack", "mern", "mean"), "fullstack"),
    (("frontend", "front end", "front-end", "ui engineer", "react"), "frontend"),
    (("backend", "back end", "back-end", "api", "server"), "backend"),
)

DEFAULT_FAMILY = "general_software"


def infer_job_family(title: str, required_skills: list[str] | None = None) -> str:
    """Pick the best job family for a title, using skills only to break a tie."""
    lowered = (title or "").lower()
    for keywords, family in _TITLE_TO_FAMILY:
        if any(keyword in lowered for keyword in keywords):
            return family

    skills = set(canonical_skills(list(required_skills or [])))
    if skills:
        best_family, best_overlap = DEFAULT_FAMILY, 0
        for family, family_skills in JOB_FAMILY_SKILLS.items():
            overlap = len(skills & set(family_skills))
            if overlap > best_overlap:
                best_family, best_overlap = family, overlap
        if best_overlap > 0:
            return best_family
    return DEFAULT_FAMILY


@dataclass(slots=True)
class VariantDraft:
    name: str
    job_family: str
    emphasised_skills: list[str]
    included_items: dict[str, Any]
    content: str
    generated_by: str = "rule_based"
    warnings: list[str] = field(default_factory=list)


def _resume_facts(resume: Resume, profile: CandidateProfile) -> dict[str, Any]:
    """Collect the only facts a variant may draw on."""
    extracted = resume.extracted_fields or {}
    return {
        "skills": canonical_skills(
            list(extracted.get("skills") or []) + list(profile.technical_skills)
        ),
        "projects": list(extracted.get("projects") or []) or list(profile.projects),
        "experience": list(extracted.get("experience") or []),
        "internships": list(extracted.get("internships") or []),
        "education": list(extracted.get("education") or []) or list(profile.education),
        "certifications": list(extracted.get("certifications") or [])
        or list(profile.certifications),
        "achievements": list(extracted.get("achievements") or []),
        "full_name": extracted.get("full_name") or profile.full_name,
        "email": extracted.get("email") or profile.email,
        "phone": extracted.get("phone") or profile.phone,
        "links": list(extracted.get("links") or []) or list(profile.links),
    }


def build_variant(
    resume: Resume,
    profile: CandidateProfile,
    job_family: str,
    *,
    emphasise: list[str] | None = None,
    name: str = "",
) -> VariantDraft:
    """Render a variant that reorders existing facts to lead with family-relevant ones."""
    facts = _resume_facts(resume, profile)
    family_skills = set(JOB_FAMILY_SKILLS.get(job_family, JOB_FAMILY_SKILLS[DEFAULT_FAMILY]))
    requested = set(canonical_skills(list(emphasise or [])))

    owned = facts["skills"]
    leading = [skill for skill in owned if skill in family_skills or skill in requested]
    trailing = [skill for skill in owned if skill not in leading]

    unsupported = sorted(requested - set(owned))
    warnings = []
    if unsupported:
        warnings.append(
            "These requested skills are not in your resume or profile and were omitted: "
            + ", ".join(unsupported)
        )

    def _project_relevance(project: dict[str, Any]) -> int:
        technologies = set(canonical_skills(list(project.get("technologies") or [])))
        text_hits = sum(
            1 for skill in family_skills if skill in str(project.get("description", "")).lower()
        )
        return len(technologies & family_skills) * 2 + text_hits

    projects = sorted(
        (project for project in facts["projects"] if isinstance(project, dict)),
        key=_project_relevance,
        reverse=True,
    )

    lines: list[str] = []
    if facts["full_name"]:
        lines.append(f"# {facts['full_name']}")
    contact = " | ".join(filter(None, [facts["email"], facts["phone"], *facts["links"][:3]]))
    if contact:
        lines.append(contact)

    lines.append("")
    lines.append(f"## Skills (ordered for {job_family.replace('_', ' ')} roles)")
    if leading:
        lines.append("**Most relevant:** " + ", ".join(leading))
    if trailing:
        lines.append("**Also:** " + ", ".join(trailing))
    if not owned:
        lines.append("_No skills were found in your resume or profile._")

    if projects:
        lines.extend(["", "## Projects"])
        for project in projects[:5]:
            title = str(project.get("name") or "Project").strip()
            description = str(project.get("description") or "").strip()
            technologies = ", ".join(str(item) for item in (project.get("technologies") or [])[:8])
            lines.append(f"- **{title}**" + (f" - {description}" if description else ""))
            if technologies:
                lines.append(f"  - Technologies: {technologies}")

    for label, key in (("Experience", "experience"), ("Internships", "internships")):
        items = [item for item in facts[key] if isinstance(item, dict)]
        if items:
            lines.extend(["", f"## {label}"])
            for item in items[:6]:
                lines.append(f"- {str(item.get('raw') or '').strip()[:300]}")

    if facts["education"]:
        lines.extend(["", "## Education"])
        for entry in facts["education"][:4]:
            if not isinstance(entry, dict):
                continue
            pieces = [
                str(entry.get("degree", "")).strip(),
                str(entry.get("institution", "")).strip(),
                str(entry.get("end_year", "")).strip(),
            ]
            rendered = " - ".join(piece for piece in pieces if piece)
            if rendered:
                lines.append(f"- {rendered}")

    if facts["certifications"]:
        lines.extend(["", "## Certifications"])
        lines.extend(f"- {str(item)[:200]}" for item in facts["certifications"][:10])

    if facts["achievements"]:
        lines.extend(["", "## Achievements"])
        lines.extend(f"- {str(item)[:250]}" for item in facts["achievements"][:10])

    lines.extend(
        [
            "",
            "---",
            "_This variant reorders facts already present in your uploaded resume and "
            "verified profile. No experience, metric or qualification has been added._",
        ]
    )

    return VariantDraft(
        name=name or f"{job_family.replace('_', ' ').title()} variant",
        job_family=job_family,
        emphasised_skills=leading,
        included_items={
            "skills": owned,
            "project_names": [str(project.get("name", "")) for project in projects[:5]],
            "education_count": len(facts["education"]),
            "certification_count": len(facts["certifications"]),
            "omitted_requested_skills": unsupported,
        },
        content="\n".join(lines),
        warnings=warnings,
    )


def audit_variant(draft: VariantDraft, resume: Resume, profile: CandidateProfile) -> list[str]:
    """Report any skill in the variant that is not in the source resume or profile.

    This is the check that makes "no fabrication" verifiable rather than asserted.
    """
    allowed = set(_resume_facts(resume, profile)["skills"])
    claimed = {
        canonical_skill(token)
        for line in draft.content.splitlines()
        if line.startswith(("**Most relevant:**", "**Also:**"))
        for token in line.split(":", 1)[-1].split(",")
    }
    unsourced = sorted(skill for skill in claimed if skill and skill not in allowed)
    return [
        f"variant claims a skill absent from your resume and profile: {skill}"
        for skill in unsourced
    ]
