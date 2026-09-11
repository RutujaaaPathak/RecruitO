# pyrefly: ignore [missing-import]
"""AI Career Recommendations service.

Turns the deterministic resume/job analysis (matched & missing skills from the
skill-gap analyzer, plus ATS and semantic scores) into a personalized career
action plan using an LLM.

The pipeline is:
    resume + target job -> matched/missing skills -> LLM -> structured plan

The LLM output is coerced into a strict, Pydantic-validated structure. If the
LLM is not configured, errors out, or returns unusable JSON, the service falls
back to deterministic rule-based recommendations built from the skill-gap data,
so the endpoint always returns a valid, structured plan.

No RAG is used: all context is provided inline in the prompt.
"""
from typing import Any, Dict, List, Optional

from app.services import llm_client
from app.services.skill_gap import RESOURCE_HINTS, analyze_skill_gap

SYSTEM_PROMPT = (
    "You are a senior career coach and technical recruiter. You produce a "
    "personalized career improvement plan for a job applicant. Respond with "
    "ONLY valid JSON, no markdown, matching the following schema exactly:\n"
    "{\n"
    '  "summary": string,\n'
    '  "priority_skills": [{"skill": string, "reason": string, '
    '"priority": "high"|"medium"|"low"}],\n'
    '  "learning_path": [{"step": string, "detail": string}],\n'
    '  "project_ideas": [{"title": string, "description": string}],\n'
    '  "resume_improvements": [string]\n'
    "}\n"
    "Keep every field concise and actionable. Ground every recommendation in "
    "the resume and the missing skills provided."
)

FALLBACK_NOTICE = (
    "The LLM recommendation service was unavailable, so these are rule-based "
    "recommendations derived from your skill-gap analysis."
)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_prompt(
    resume_text: str,
    job_title: Optional[str],
    job_skills: Optional[List[str]],
    job_description: Optional[str],
    matched_skills: List[str],
    missing_skills: List[str],
    ats_score: Optional[int],
    semantic_score: Optional[int],
) -> str:
    """Compose the prompt that feeds structured context into the LLM."""
    ats = f"{ats_score}/100" if ats_score is not None else "N/A"
    semantic = f"{semantic_score}/100" if semantic_score is not None else "N/A"
    return f"""{SYSTEM_PROMPT}

JOB TITLE: {job_title or "N/A"}

JOB DESCRIPTION:
{job_description or "N/A"}

REQUIRED SKILLS:
{", ".join(job_skills) if job_skills else "None listed"}

RESUME TEXT:
{resume_text or "N/A"}

MATCHED SKILLS (already present in the resume):
{", ".join(matched_skills) if matched_skills else "None"}

MISSING SKILLS (required by the job but not in the resume):
{", ".join(missing_skills) if missing_skills else "None - the candidate may already meet all requirements"}

EXISTING ATS MATCH SCORE: {ats}
EXISTING SEMANTIC SIMILARITY SCORE: {semantic}

Now produce the personalized career recommendation JSON."""


# ---------------------------------------------------------------------------
# Lenient coercion of LLM output
# ---------------------------------------------------------------------------

_PRIORITIES = {"high", "medium", "low"}


def _priority(value: Any) -> str:
    v = str(value or "medium").lower().strip()
    return v if v in _PRIORITIES else "medium"


def _coerce_priority_skills(raw: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, str):
            item = {"skill": item}
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or item.get("name") or "").strip()
        if not skill:
            continue
        out.append(
            {
                "skill": skill,
                "reason": str(item.get("reason") or item.get("explanation") or ""),
                "priority": _priority(item.get("priority")),
            }
        )
    return out


def _coerce_learning_path(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"step": item, "detail": ""})
        elif isinstance(item, dict):
            step = str(
                item.get("step") or item.get("title") or item.get("name") or ""
            )
            if step:
                out.append({"step": step, "detail": str(item.get("detail") or "")})
    return out


def _coerce_project_ideas(raw: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, str):
            out.append({"title": item, "description": ""})
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("name") or "")
            if title:
                out.append({"title": title, "description": str(item.get("description") or "")})
    return out


def _coerce_strings(raw: Any) -> List[str]:
    out: List[str] = []
    for item in raw or []:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def parse_llm_recommendations(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a raw LLM JSON object into a structured plan.

    Tolerant of imperfect LLM output: unknown fields are dropped, missing
    optional fields default to empty lists, and strings/objects are accepted
    where nested items are expected. The result is fully serializable and safe
    to construct a Pydantic response model from.
    """
    if not isinstance(data, dict):
        return {
            "summary": "",
            "priority_skills": [],
            "learning_path": [],
            "project_ideas": [],
            "resume_improvements": [],
        }
    return {
        "summary": str(data.get("summary") or "").strip(),
        "priority_skills": _coerce_priority_skills(data.get("priority_skills")),
        "learning_path": _coerce_learning_path(data.get("learning_path")),
        "project_ideas": _coerce_project_ideas(data.get("project_ideas")),
        "resume_improvements": _coerce_strings(data.get("resume_improvements")),
    }


# ---------------------------------------------------------------------------
# Rule-based fallback (no LLM)
# ---------------------------------------------------------------------------

def build_fallback_recommendations(
    matched_skills: List[str],
    missing_skills: List[str],
    ats_score: Optional[int] = None,
    semantic_score: Optional[int] = None,
) -> Dict[str, Any]:
    """Deterministic plan derived purely from the skill-gap analysis."""
    priority_skills = [
        {
            "skill": skill,
            "reason": RESOURCE_HINTS.get(
                skill,
                "This required skill is missing from your resume for this role.",
            ),
            "priority": "high",
        }
        for skill in missing_skills
    ]

    if missing_skills:
        learning_path = [
            {
                "step": f"Learn the fundamentals of {skill}.",
                "detail": RESOURCE_HINTS.get(
                    skill, "Start with official documentation and beginner tutorials."
                ),
            }
            for skill in missing_skills[:3]
        ]
        learning_path.append(
            {
                "step": "Integrate the new skills into a portfolio project.",
                "detail": "Build one small project that uses the skills above, "
                "then add it to your resume in the Projects section.",
            }
        )
        first = missing_skills[0]
        project_ideas = [
            {
                "title": f"Portfolio app showcasing {first}.",
                "description": (
                    f"A small end-to-end project that demonstrates {first} and "
                    "covers it with tests and documentation. "
                    "Publish it with a clean README."
                ),
            },
            {
                "title": "Contribute to an open-source repository.",
                "description": (
                    "Pick a popular project in the target stack and fix a "
                    "beginner-friendly issue to get real-world experience with "
                    "the missing skills."
                ),
            },
        ]
    else:
        learning_path = [
            {
                "step": "Deepen your existing strengths.",
                "detail": "You already match all required skills. Focus on "
                "senior-level depth, architecture, and measurable outcomes.",
            }
        ]
        project_ideas = [
            {
                "title": "Senior-level showcase project.",
                "description": (
                    "Build a project that demonstrates architecture, testing, "
                    "and observability for the skills on the job description."
                ),
            }
        ]

    resume_improvements = [
        "Quantify achievements (numbers, impact, scale) so recruiters can "
        "gauge the depth of your experience.",
        "Ensure every required skill that you possess appears verbatim (or "
        "near-verbatim) in your resume; automatic systems scan for them.",
        "Add a short 'Relevant Skills' summary near the top tailored to each "
        "target job.",
    ]
    if missing_skills:
        resume_improvements.append(
            "Show partial experience with missing skills (side projects, "
            "training) on your resume to demonstrate commitment to growth."
        )

    summary = _fallback_summary(matched_skills, missing_skills, ats_score, semantic_score)
    return {
        "summary": summary,
        "priority_skills": priority_skills,
        "learning_path": learning_path,
        "project_ideas": project_ideas,
        "resume_improvements": resume_improvements,
    }


def _fallback_summary(
    matched_skills: List[str],
    missing_skills: List[str],
    ats_score: Optional[int],
    semantic_score: Optional[int],
) -> str:
    parts = []
    if ats_score is not None and semantic_score is not None:
        parts.append(
            f"Your ATS match is {ats_score}% and your semantic similarity is "
            f"{semantic_score}%."
        )
    elif ats_score is not None:
        parts.append(f"Your ATS match is {ats_score}%.")
    elif semantic_score is not None:
        parts.append(f"Your semantic similarity is {semantic_score}%.")
    if missing_skills:
        parts.append(
            f"You have {len(missing_skills)} missing required skill"
            f"{'s' if len(missing_skills) > 1 else ''}; closing these gaps will "
            "strengthen your application."
        )
    else:
        parts.append(
            "You already cover every required skill; focus on demonstrating "
            "depth and senior impact."
        )
    return " ".join(parts) + " (Rule-based plan.)"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_career_recommendations(
    resume_text: str,
    job_skills: Optional[List[str]],
    job_description: Optional[str],
    job_title: Optional[str] = None,
    ats_score: Optional[int] = None,
    semantic_score: Optional[int] = None,
    llm_call=None,
) -> Dict[str, Any]:
    """Produce a career recommendations plan for a resume against a job.

    The skill-gap analysis is always run first (existing logic, unchanged).
    The LLM is then asked to personalize the plan; on any failure a rule-based
    fallback is returned. `llm_call` is injectable for tests and defaults to
    the production LLM client's `generate_json`.

    Returns a dict serializable through the `CareerRecommendationsOut` schema.
    """
    gap = analyze_skill_gap(resume_text, job_skills, job_description)
    matched_skills = gap.matched_skills
    missing_skills = [m.skill for m in gap.missing_skills]

    if llm_call is None:
        llm_call = llm_client.generate_json

    try:
        prompt = build_prompt(
            resume_text=resume_text,
            job_title=job_title,
            job_skills=job_skills,
            job_description=job_description,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            ats_score=ats_score,
            semantic_score=semantic_score,
        )
        raw = llm_call(prompt, system=SYSTEM_PROMPT)
        plan = parse_llm_recommendations(raw)
        if not any(
            plan[key]
            for key in (
                "priority_skills",
                "learning_path",
                "project_ideas",
                "resume_improvements",
                "summary",
            )
        ):
            raise ValueError("LLM returned an empty plan.")
        plan["generated_by"] = "llm"
        plan["notice"] = None
        plan["matched_skills"] = matched_skills
        plan["missing_skills"] = missing_skills
        return plan
    except Exception as exc:
        plan = build_fallback_recommendations(
            matched_skills, missing_skills, ats_score, semantic_score
        )
        plan["generated_by"] = "fallback"
        plan["notice"] = f"{FALLBACK_NOTICE} ({_safe_reason(exc)})"
        plan["matched_skills"] = matched_skills
        plan["missing_skills"] = missing_skills
        return plan


def _safe_reason(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:300]