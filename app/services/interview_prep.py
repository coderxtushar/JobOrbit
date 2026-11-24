"""Interview preparation, mock-interview practice and the user's own round records.

Preparation is built deterministically from three inputs and says, item by item, which one
it came from: the job (its skills and description sections), the candidate's own profile
and resume (skills, experience, education, projects — their stated details only), and the
cited company profile from :mod:`app.services.company_research`. No LLM is needed, and the
default path never calls one.

Two lines are not crossed:

* A skill the job needs and the profile lacks is a *topic to prepare*, phrased as such. It
  is never turned into a question that presumes the candidate has used it.
* Interview rounds are the user's records. Nothing here generates an outcome, interviewer
  feedback or a next step for a round, and practice feedback is labelled as rule-based
  structure checks, not a judgement from an interviewer.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.db.models import (
    Application,
    CandidateProfile,
    InterviewPrep,
    InterviewRound,
    Job,
    Outcome,
    Resume,
    utcnow,
)
from app.services.company_research import (
    NOT_STATED,
    build_company_profile,
    is_heading,
    project_skills,
)
from app.services.evidence import analyse_description
from app.services.resume_variants import infer_job_family
from app.services.text import canonical_skills, collapse_whitespace

SECTION_ORDER: tuple[str, ...] = (
    "technical",
    "resume",
    "projects",
    "behavioural",
    "coding",
    "company",
    "skill_gaps",
)
#: Sections whose items are questions to answer aloud; the rest are topics to study.
PRACTICE_SECTIONS: tuple[str, ...] = ("technical", "resume", "projects", "behavioural")

FEEDBACK_DISCLAIMER = (
    "Automatic, rule-based feedback on length, structure and coverage only. It is not a "
    "grade from a human interviewer and does not judge whether the answer is correct."
)

#: Skill-specific technical prompts. Anything absent falls back to a generic template.
_SKILL_QUESTIONS: dict[str, str] = {
    "python": "How do Python's lists, dicts and generators differ in memory use and when "
    "would you choose each?",
    "java": "Explain the difference between an interface and an abstract class in Java, "
    "and when you would use each.",
    "javascript": "Explain the JavaScript event loop and how promises and async/await fit into it.",
    "typescript": "What does TypeScript's type system catch that tests might not, and where "
    "does it stop helping?",
    "sql": "Write a query that returns the top three rows per group, and explain how a "
    "window function does it.",
    "postgresql": "How would you find and fix a slow PostgreSQL query? What does EXPLAIN "
    "ANALYZE tell you?",
    "mysql": "How do indexes work in MySQL, and when does an index not help a query?",
    "mongodb": "When would you choose MongoDB over a relational database, and what do you give up?",
    "fastapi": "How does FastAPI use type hints for validation and dependency injection?",
    "django": "Explain Django's ORM query evaluation. How would you avoid N+1 queries?",
    "flask": "How would you structure a Flask application as it grows beyond one file?",
    "react": "Explain React's rendering cycle. When does a component re-render, and how "
    "would you prevent unnecessary renders?",
    "node.js": "How does Node.js handle concurrency on a single thread, and what blocks it?",
    "docker": "What is the difference between an image and a container, and how would you "
    "keep an image small?",
    "kubernetes": "Explain pods, deployments and services in Kubernetes and how traffic "
    "reaches a pod.",
    "aws": "Which AWS services would you use to deploy a simple web API, and why?",
    "git": "How do you resolve a merge conflict, and when would you rebase instead of merge?",
    "rest api": "What makes an API RESTful? How would you version one and handle errors?",
    "system design": "Design a URL shortener: walk through the API, storage and scaling.",
    "machine learning": "How do you detect and handle overfitting in a model?",
    "llm": "How would you evaluate an LLM-based feature, and how would you reduce hallucinations?",
    "langchain": "What problem does LangChain solve, and when would you not use it?",
    "redis": "When would you use Redis as a cache, and how would you handle cache invalidation?",
    "kafka": "What guarantees does Kafka give about ordering and delivery?",
    "linux": "How would you find out which process is using the most memory on a Linux server?",
    "data structures": "When would you use a hash map versus a balanced tree?",
    "testing": "How do you decide what to unit test versus integration test?",
}

_CODING_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "backend": (
        "Arrays, strings and hash maps (two pointers, sliding window)",
        "SQL joins, aggregation and indexing",
        "API design and error handling",
        "Concurrency basics: threads, async I/O, race conditions",
    ),
    "frontend": (
        "DOM manipulation and event handling in plain JavaScript",
        "Implementing debounce/throttle and a small component from scratch",
        "Arrays, strings and hash maps",
        "Browser rendering and performance basics",
    ),
    "fullstack": (
        "Arrays, strings and hash maps",
        "SQL joins and aggregation",
        "Building a small CRUD feature end to end",
        "JavaScript async patterns",
    ),
    "data": (
        "SQL: window functions, joins, aggregation",
        "Data cleaning with Python (pandas or plain Python)",
        "Arrays, hash maps and sorting",
    ),
    "ai_ml": (
        "Python and NumPy array manipulation",
        "Implementing a basic model evaluation (train/test split, metrics) by hand",
        "Arrays, hash maps, sorting and searching",
        "Probability and statistics fundamentals",
    ),
    "genai": (
        "Python: strings, dicts and JSON handling",
        "Calling an HTTP API with retries and timeouts",
        "Chunking text and simple retrieval (similarity search) logic",
        "Arrays, hash maps and sorting",
    ),
    "cloud_devops": (
        "Shell scripting and Linux command-line problems",
        "Writing a small automation script in Python",
        "Networking basics: DNS, HTTP, TLS",
        "Arrays, strings and hash maps",
    ),
    "general_software": (
        "Arrays, strings and hash maps",
        "Linked lists, stacks and queues",
        "Trees and graphs (BFS/DFS)",
        "Sorting, searching and Big-O analysis",
    ),
}

_BEHAVIOURAL_BASE: tuple[str, ...] = (
    "Tell me about yourself and why you are interested in this role.",
    "Describe a time you had to learn a new technology quickly. How did you approach it?",
    "Tell me about a time something you built did not work as expected. What did you do?",
    "Describe a disagreement with a teammate and how it was resolved.",
    "Tell me about a time you had to deliver under a tight deadline.",
)
_BEHAVIOURAL_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "backend": ("Describe how you debugged a difficult production or integration issue.",),
    "frontend": ("Tell me about a time user feedback changed something you built.",),
    "fullstack": ("Describe a feature you owned from the database to the UI.",),
    "data": ("Tell me about a time you found a problem in the data you were given.",),
    "ai_ml": ("Tell me about a time a model's results surprised you. How did you investigate?",),
    "genai": ("Describe how you checked that an AI feature's output could be trusted.",),
    "cloud_devops": ("Describe an outage or failed deployment and what you changed afterwards.",),
    "general_software": ("Tell me about a piece of code you are proud of and why.",),
}

_STAR_SIGNALS: dict[str, tuple[str, ...]] = {
    "situation": (
        "when i",
        "while i",
        "at my",
        "during",
        "situation",
        "context",
        "was working",
        "in my",
        "last year",
        "project",
    ),
    "task": (
        "task",
        "goal",
        "needed to",
        "had to",
        "responsible",
        "my role",
        "asked to",
        "challenge",
    ),
    "action": (
        "i built",
        "i decided",
        "i implemented",
        "i wrote",
        "i led",
        "i created",
        "i designed",
        "i fixed",
        "i used",
        "i added",
        "i changed",
        "i started",
        "so i",
        "i then",
        "action",
    ),
    "result": (
        "result",
        "outcome",
        "as a result",
        "led to",
        "reduced",
        "improved",
        "increased",
        "saved",
        "learned",
        "in the end",
        "finally",
    ),
}
_EXAMPLE_SIGNALS = ("for example", "for instance", "e.g.", "in my project", "i used", "i built")


def _item_id(kind: str, text: str) -> str:
    """Stable id, so a regenerated prep keeps practice history attached to its question."""
    digest = hashlib.sha1(f"{kind}:{text}".encode(), usedforsecurity=False).hexdigest()[:10]
    return f"{kind}-{digest}"


def _item(kind: str, question: str, derived_from: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": _item_id(kind, question),
        "kind": kind,
        "question": question,
        "derived_from": derived_from,
        **extra,
    }


def _primary_resume(session: Session, profile: CandidateProfile) -> Resume | None:
    return session.scalar(
        select(Resume)
        .where(Resume.profile_id == profile.id)
        .order_by(Resume.is_primary.desc(), Resume.created_at.desc())
        .limit(1)
    )


def _responsibility_lines(description: str, limit: int = 3) -> list[str]:
    """Bullets under a responsibilities heading, verbatim, for role-specific questions."""
    lines: list[str] = []
    inside = False
    for raw_line in (description or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        bullet = line[:1] in "•-*·" or bool(re.match(r"\d+[.)]\s", line))
        if not bullet and any(
            cue in lowered for cue in ("responsibilit", "what you'll do", "what you will do")
        ):
            inside = True
            continue
        if inside and not bullet and (is_heading(line) or line.isupper()):
            break
        if inside:
            cleaned = collapse_whitespace(line.lstrip("•-*· \t"))
            if 4 <= len(cleaned.split()) <= 40:
                lines.append(cleaned)
        if len(lines) >= limit:
            break
    return lines


def _profile_facts(session: Session, profile: CandidateProfile) -> dict[str, Any]:
    resume = _primary_resume(session, profile)
    extracted = (resume.extracted_fields if resume is not None else None) or {}
    return {
        "skills": canonical_skills(
            list(profile.technical_skills) + list(extracted.get("skills") or [])
        ),
        "projects": [p for p in (profile.projects or extracted.get("projects") or []) if p],
        "education": list(profile.education or extracted.get("education") or []),
        "experience": list(extracted.get("experience") or []),
        "internships": list(extracted.get("internships") or []),
        "certifications": list(profile.certifications or extracted.get("certifications") or []),
        "years_experience": profile.years_experience,
        "projects_from": "your profile" if profile.projects else "your resume",
    }


def _technical(job: Job, required: list[str], preferred: list[str]) -> list[dict[str, Any]]:
    evidence = analyse_description(job.description)
    items: list[dict[str, Any]] = []
    for level, skills in (("required", required[:8]), ("preferred", preferred[:4])):
        for skill in skills:
            question = _SKILL_QUESTIONS.get(skill) or (
                f"What are the core concepts of {skill}, and how would you apply them in "
                f"a {job.title} role?"
            )
            span = evidence.spans.get(skill)
            derived = f"{level} skill '{skill}' in the listing" + (f': "{span}"' if span else "")
            items.append(_item("technical", question, derived, skill=skill))
    for line in _responsibility_lines(job.description):
        items.append(
            _item(
                "technical",
                f'The role involves: "{line}". How would you approach this?',
                "responsibilities section of the listing",
            )
        )
    return items


def _resume_questions(facts: dict[str, Any], job_skills: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    matched = [skill for skill in facts["skills"] if skill in set(job_skills)]
    for skill in matched[:5]:
        items.append(
            _item(
                "resume",
                f"Your profile lists {skill}. Walk me through something you built or "
                f"solved with it.",
                f"'{skill}' is in your profile's skills and in the listing",
                skill=skill,
            )
        )
    years = facts.get("years_experience") or 0
    if years and years > 0:
        items.append(
            _item(
                "resume",
                f"Your profile records about {years:g} year{'' if years == 1 else 's'} of "
                "experience. Which of it is most relevant to this role, and why?",
                f"years of experience in your profile ({years:g})",
            )
        )
    for role in (facts["experience"] + facts["internships"])[:3]:
        raw = collapse_whitespace(str(role.get("raw", "") if isinstance(role, dict) else role))
        if not raw:
            continue
        items.append(
            _item(
                "resume",
                f'Tell me about this entry on your resume: "{raw[:160]}". What was your '
                "contribution?",
                "experience section of your resume",
            )
        )
    for entry in facts["education"][:2]:
        if not isinstance(entry, dict):
            continue
        degree = str(entry.get("degree") or "").strip()
        institution = str(entry.get("institution") or "").strip()
        if not degree and not institution:
            continue
        label = " at ".join(part for part in (degree, institution) if part)
        items.append(
            _item(
                "resume",
                f"What from your {label} prepared you best for this role?",
                "education in your profile",
            )
        )
    for certification in facts["certifications"][:2]:
        items.append(
            _item(
                "resume",
                f"What did you learn earning '{certification}', and have you applied it?",
                "certifications in your profile",
            )
        )
    return items


def _project_questions(facts: dict[str, Any], job_skills: list[str]) -> list[dict[str, Any]]:
    wanted = set(job_skills)
    ranked: list[tuple[int, dict[str, Any], list[str]]] = []
    for project in facts["projects"]:
        if not isinstance(project, dict) or not str(project.get("name") or "").strip():
            continue
        stack = project_skills(project)
        overlap = [skill for skill in stack if skill in wanted]
        ranked.append((len(overlap), project, stack))
    ranked.sort(key=lambda item: -item[0])

    items: list[dict[str, Any]] = []
    for overlap_count, project, stack in ranked[:3]:
        name = collapse_whitespace(str(project["name"]))
        source = f"your project '{name}' ({facts['projects_from']})"
        items.append(
            _item(
                "projects",
                f"Walk me through {name}: what problem did it solve, and what was your part?",
                source,
                project=name,
            )
        )
        if stack:
            tech = stack[0]
            items.append(
                _item(
                    "projects",
                    f"Why did you use {tech} in {name}, and what alternatives did you consider?",
                    f"{source}; its stated technologies include {', '.join(stack[:4])}",
                    project=name,
                    skill=tech,
                )
            )
        items.append(
            _item(
                "projects",
                f"If {name} had ten times the users or data, what would break first and how "
                "would you change it?",
                source
                + (f"; overlaps the listing on {overlap_count} skill(s)" if overlap_count else ""),
                project=name,
            )
        )
    return items


def _behavioural(family: str) -> list[dict[str, Any]]:
    items = [_item("behavioural", q, "standard behavioural question") for q in _BEHAVIOURAL_BASE]
    for question in _BEHAVIOURAL_BY_FAMILY.get(family, ()):
        items.append(_item("behavioural", question, f"tailored to job family '{family}'"))
    return items


def _coding(family: str, required: list[str]) -> list[dict[str, Any]]:
    items = [
        _item("coding", topic, f"typical for job family '{family}' (inferred from the title)")
        for topic in _CODING_BY_FAMILY.get(family, _CODING_BY_FAMILY["general_software"])
    ]
    skill_topics = {
        "sql": "SQL practice: joins, GROUP BY, window functions",
        "python": "Python practice: comprehensions, generators, standard library collections",
        "javascript": "JavaScript practice: closures, promises, array methods",
        "java": "Java practice: collections framework, streams, OOP design",
        "data structures": "Data structures: implement a stack, queue and hash map",
        "system design": "System design practice: one end-to-end design a day",
    }
    for skill in required:
        if skill in skill_topics:
            items.append(_item("coding", skill_topics[skill], f"required skill '{skill}'"))
    return items


def _company(research: dict[str, Any]) -> list[dict[str, Any]]:
    data = research.get("data") or {}
    name = research.get("company") or "the company"
    items: list[dict[str, Any]] = []
    for about in (data.get("about") or [])[:1]:
        items.append(
            _item(
                "company",
                f"Read how {name} describes itself and be ready to say why it interests you: "
                f'"{about["quote"][:240]}"',
                f"{about['where']} of a listing",
                source=about["source"],
            )
        )
    for key, label in (("business_model", "business model"), ("products", "products")):
        block = data.get(key) or {}
        if block.get("stated"):
            fact = block["facts"][0]
            items.append(
                _item(
                    "company",
                    f'A cited source states its {label}: "{fact["quote"].rstrip(".")}". '
                    "Think about what that means for the engineering work.",
                    f"stated {label} in a cited source",
                    source=fact["source"],
                )
            )
        else:
            items.append(
                _item(
                    "company",
                    f"The company's {label} is {NOT_STATED}. Look it up on the company's "
                    "own site before the interview rather than guessing.",
                    f"no {label} statement in the listings JobOrbit holds",
                )
            )
    technologies = data.get("technologies") or []
    if technologies:
        top = ", ".join(f"{t['skill']} ({t['listing_count']})" for t in technologies[:6])
        items.append(
            _item(
                "company",
                f"Technologies across this company's listings: {top}.",
                f"skills counted across {data.get('listing_count', 0)} listing(s)",
            )
        )
    for theme in (data.get("engineering_focus") or [])[:3]:
        items.append(
            _item(
                "company",
                f"Engineering focus: {theme['theme']}. Prepare an example or a view on it.",
                "listings mention " + ", ".join(f"'{p}'" for p in theme["phrases"][:4]),
            )
        )
    return items


def _skill_gaps(required: list[str], preferred: list[str], have: list[str]) -> list[dict[str, Any]]:
    owned = set(have)
    items: list[dict[str, Any]] = []
    for level, skills in (("required", required), ("preferred", preferred)):
        for skill in skills:
            if skill in owned:
                continue
            items.append(
                _item(
                    "skill_gaps",
                    f"Prepare {skill} fundamentals. The listing marks it {level} and your "
                    "profile does not list it; if asked, describe your actual level honestly.",
                    f"{level} skill '{skill}' in the listing, absent from your profile",
                    skill=skill,
                    level=level,
                )
            )
    return items


def _job_skill_lists(job: Job) -> tuple[list[str], list[str]]:
    evidence = analyse_description(job.description)
    required = canonical_skills(list(job.required_skills) + evidence.required)
    preferred = [
        skill
        for skill in canonical_skills(list(job.preferred_skills) + evidence.preferred)
        if skill not in required
    ]
    return required, preferred


def build_prep_content(
    session: Session, application: Application, profile: CandidateProfile
) -> dict[str, Any]:
    """Assemble the preparation document. Deterministic: same inputs, same content."""
    job = application.job
    required, preferred = _job_skill_lists(job)
    family = infer_job_family(job.title, required)
    facts = _profile_facts(session, profile)
    research = build_company_profile(session, job.company, job=job, profile=profile).to_dict()

    sections: dict[str, list[dict[str, Any]]] = {
        "technical": _technical(job, required, preferred),
        "resume": _resume_questions(facts, required + preferred),
        "projects": _project_questions(facts, required + preferred),
        "behavioural": _behavioural(family),
        "coding": _coding(family, required),
        "company": _company(research),
        "skill_gaps": _skill_gaps(required, preferred, facts["skills"]),
    }
    notes = [
        "Every item names what it was derived from. Nothing here is a fact about your "
        "background that your profile or resume does not already state.",
        "Skill gaps are topics to prepare, not claims to make.",
    ]
    if not facts["projects"]:
        notes.append("No projects are recorded in your profile, so there are no project questions.")
    return {
        "application_id": application.id,
        "job": {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "family": family,
            "required_skills": required,
            "preferred_skills": preferred,
        },
        "generated_by": "rule_based",
        "generated_at": utcnow().isoformat(),
        "sections": sections,
        "notes": notes,
    }


def build_prep(
    session: Session, application: Application, *, regenerate: bool = False
) -> InterviewPrep:
    """Return the stored prep for an application, generating it on first use.

    ``regenerate`` rebuilds the content but keeps practice history: the user's answers are
    their record, and stable item ids keep them attached to unchanged questions.
    """
    prep = session.scalar(
        select(InterviewPrep).where(InterviewPrep.application_id == application.id)
    )
    if prep is not None and not regenerate:
        return prep
    profile = session.get(CandidateProfile, application.profile_id)
    if profile is None:  # pragma: no cover - FK guarantees it
        raise ValueError("application has no profile")
    content = build_prep_content(session, application, profile)
    if prep is None:
        prep = InterviewPrep(application_id=application.id, content=content, practice=[])
        session.add(prep)
    else:
        prep.content = content
        prep.generated_at = utcnow()
    session.flush()
    return prep


def get_prep(session: Session, application_id: int) -> InterviewPrep | None:
    return session.scalar(
        select(InterviewPrep).where(InterviewPrep.application_id == application_id)
    )


# --------------------------------------------------------------------------------------
# Mock interview
# --------------------------------------------------------------------------------------


def practice_items(prep: InterviewPrep) -> list[dict[str, Any]]:
    sections = (prep.content or {}).get("sections") or {}
    return [item for key in PRACTICE_SECTIONS for item in sections.get(key) or []]


def find_item(prep: InterviewPrep, question_id: str) -> dict[str, Any] | None:
    sections = (prep.content or {}).get("sections") or {}
    for key in SECTION_ORDER:
        for item in sections.get(key) or []:
            if item.get("id") == question_id:
                return dict(item)
    return None


def next_practice_question(
    prep: InterviewPrep, *, kind: str | None = None, after: str | None = None
) -> dict[str, Any] | None:
    """The next question to practise: unanswered first, then the least practised.

    Sections are interleaved (technical, resume, project, behavioural, ...) so a session
    does not spend its first ten questions on one kind. ``after`` skips past a question id,
    for a "next" button that should not repeat the one just shown.
    """
    if kind is not None:
        pool = [item for item in practice_items(prep) if item.get("kind") == kind]
    else:
        sections = (prep.content or {}).get("sections") or {}
        queues = [list(sections.get(key) or []) for key in PRACTICE_SECTIONS]
        pool = []
        while any(queues):
            for queue in queues:
                if queue:
                    pool.append(queue.pop(0))
    if not pool:
        return None
    counts: dict[str, int] = {}
    for entry in prep.practice or []:
        counts[entry.get("question_id", "")] = counts.get(entry.get("question_id", ""), 0) + 1
    candidates = [item for item in pool if item.get("id") != after] or pool
    best = min(candidates, key=lambda item: counts.get(item["id"], 0))
    return {**best, "times_practised": counts.get(best["id"], 0)}


def _contains_any(text: str, phrases: tuple[str, ...] | list[str]) -> list[str]:
    return [
        phrase
        for phrase in phrases
        if re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text)
    ]


def practice_feedback(item: dict[str, Any], answer: str, job_skills: list[str]) -> dict[str, Any]:
    """Rule-based feedback on an answer: length, structure and coverage. Not a grade."""
    text = collapse_whitespace(answer or "")
    lowered = text.lower()
    words = len(text.split())
    kind = item.get("kind", "")
    points: list[str] = []
    checks: dict[str, Any] = {"word_count": words}

    if words == 0:
        points.append("No answer was given.")
    elif words < 40:
        points.append(
            f"At {words} words this is short for a spoken answer; aim for roughly 80-250."
        )
    elif words > 350:
        points.append(
            f"At {words} words this may run long when spoken; try to keep the core under 250."
        )
    else:
        points.append(f"Length ({words} words) is reasonable for a spoken answer.")

    if kind in ("behavioural", "projects", "resume"):
        star = {part: bool(_contains_any(lowered, cues)) for part, cues in _STAR_SIGNALS.items()}
        checks["star"] = star
        missing = [part for part, present in star.items() if not present]
        if kind == "behavioural" or missing != list(star):
            if missing:
                points.append(
                    "STAR structure: no clear signal of "
                    + ", ".join(missing)
                    + ". Say what the situation was, what you had to do, what you did and "
                    "what happened."
                )
            else:
                points.append("STAR structure: situation, task, action and result all appear.")
        if " i " not in f" {lowered} " and words:
            points.append("Say what *you* did ('I ...'), not only what the team did.")

    if kind in ("technical", "projects", "resume"):
        skills = list(dict.fromkeys([s for s in [item.get("skill")] if s] + job_skills))
        mentioned = _contains_any(lowered, skills)
        checks["skills_mentioned"] = mentioned
        if item.get("skill") and item["skill"] not in mentioned:
            points.append(f"The question is about {item['skill']}, but the answer never names it.")
        elif mentioned:
            points.append("Mentions the job's skills: " + ", ".join(mentioned[:6]) + ".")
        example = bool(_contains_any(lowered, _EXAMPLE_SIGNALS))
        checks["has_example"] = example
        if not example and words:
            points.append("Add a concrete example ('for example, in my project ...').")

    if re.search(r"\d", text):
        checks["has_numbers"] = True
    elif kind in ("behavioural", "projects") and words:
        points.append("If you can, quantify the result (time saved, users, error rate).")

    return {"points": points, "checks": checks, "disclaimer": FEEDBACK_DISCLAIMER}


def record_practice(
    session: Session, prep: InterviewPrep, question: dict[str, Any] | str, answer: str
) -> dict[str, Any]:
    """Store one practice answer with its rule-based feedback, and return the feedback."""
    item = find_item(prep, question) if isinstance(question, str) else dict(question)
    if item is None:
        raise KeyError(f"no question {question!r} in this preparation")
    job = (prep.content or {}).get("job") or {}
    job_skills = list(job.get("required_skills") or []) + list(job.get("preferred_skills") or [])
    feedback = practice_feedback(item, answer, job_skills)
    entry = {
        "question_id": item.get("id", ""),
        "kind": item.get("kind", ""),
        "question": item.get("question", ""),
        "answer": (answer or "")[:5000],
        "feedback": feedback,
        "answered_at": utcnow().isoformat(),
    }
    # Reassign rather than append: a JSON column only notices a new list object.
    prep.practice = [*(prep.practice or []), entry]
    session.flush()
    return feedback


# --------------------------------------------------------------------------------------
# Interview rounds — the user's own records
# --------------------------------------------------------------------------------------

ROUND_FIELDS: tuple[str, ...] = (
    "round_name",
    "scheduled_at",
    "interviewer_notes",
    "questions_asked",
    "feedback",
    "next_steps",
)


def _clean_round_values(values: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if key not in ROUND_FIELDS:
            continue
        if key == "questions_asked":
            value = [str(q).strip() for q in (value or []) if str(q).strip()][:50]
        elif key == "scheduled_at":
            if value is not None and not isinstance(value, datetime):
                raise ValueError("scheduled_at must be a datetime")
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError("scheduled_at must include a timezone")
        elif value is None:
            value = ""
        cleaned[key] = value
    return cleaned


def list_rounds(session: Session, application_id: int) -> list[InterviewRound]:
    statement = (
        select(InterviewRound)
        .where(InterviewRound.application_id == application_id)
        .order_by(InterviewRound.scheduled_at.is_(None), InterviewRound.scheduled_at)
        .order_by(InterviewRound.id)
    )
    return list(session.scalars(statement))


def get_round(session: Session, round_id: int) -> InterviewRound | None:
    return session.get(InterviewRound, round_id)


def create_round(
    session: Session, application: Application, values: dict[str, Any]
) -> InterviewRound:
    """Record a round exactly as the user described it."""
    record = InterviewRound(application_id=application.id, **_clean_round_values(values))
    session.add(record)
    session.flush()
    return record


def update_round(
    session: Session, record: InterviewRound, values: dict[str, Any]
) -> InterviewRound:
    for key, value in _clean_round_values(values).items():
        setattr(record, key, value)
    record.updated_at = utcnow()
    session.flush()
    return record


def delete_round(session: Session, record: InterviewRound) -> None:
    session.delete(record)
    session.flush()


def is_interview_stage(application: Application) -> bool:
    """Whether the application has reached interviews, by outcome or by a recorded round."""
    if application.outcome in (Outcome.SCREENING, Outcome.INTERVIEWING):
        return True
    session = object_session(application)
    if session is None:
        return False
    return (
        session.scalar(
            select(InterviewRound.id)
            .where(InterviewRound.application_id == application.id)
            .limit(1)
        )
        is not None
    )


__all__ = [
    "FEEDBACK_DISCLAIMER",
    "PRACTICE_SECTIONS",
    "SECTION_ORDER",
    "build_prep",
    "build_prep_content",
    "create_round",
    "delete_round",
    "find_item",
    "get_prep",
    "get_round",
    "is_interview_stage",
    "list_rounds",
    "next_practice_question",
    "practice_feedback",
    "practice_items",
    "record_practice",
    "update_round",
]
