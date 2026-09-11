# RecruitO – AI Powered Recruitment and Career Intelligence Platform

## Overview

RecruitO is an AI-powered full-stack recruitment platform designed to transform the hiring process through intelligent automation, resume analysis, skill gap detection, AI-generated assessments, and AI-powered interviews.

The platform creates an ecosystem where job seekers can discover opportunities, improve their skills, and companies can recruit candidates more efficiently.

---

# Problem Statement

Traditional recruitment systems often face challenges such as:

* Inefficient resume screening
* Poor candidate-job matching
* Lack of personalized guidance for skill improvement
* Time-consuming recruitment processes
* Difficulty evaluating candidate preparedness

RecruitO aims to solve these problems through AI-driven recruitment workflows.

---

# Features

## User Module

Users can:

* Create accounts
* Select up to 5 career domains
* Upload resumes
* Build professional profiles
* Add educational and skill details
* Apply for jobs
* Attend AI-powered mock interviews
* Participate in company interviews

### Supported Domains

Examples include:

* Artificial Intelligence
* Machine Learning
* Software Development
* Web Development
* Data Science
* Cybersecurity
* Cloud Computing

---

## Company Module

Companies can:

* Create company profiles
* Add job roles and vacancies
* Update vacancies in real time
* Define requirements for job positions
* Review applications
* View candidate matching percentages
* Conduct interviews directly on the platform

---

## Admin Module

Admin functionalities include:

* User management
* Company management
* Monitoring platform activities
* Fraud detection
* Managing restricted users
* Platform analytics

---

# Intelligent Features

## Resume Analysis

The system automatically:

* Extracts resume information
* Compares resumes with job requirements
* Calculates matching percentages
* Identifies missing skills
* Provides improvement suggestions

---

## AI Skill Gap Analysis

RecruitO helps candidates by:

* Detecting missing technical skills
* Finding resume weaknesses
* Identifying knowledge gaps
* Suggesting learning resources

---

## AI Generated Assessment Tests

When candidates satisfy minimum matching requirements:

* AI generates 20 dynamic questions
* Questions change for every attempt
* Candidates must satisfy minimum passing criteria
* Qualified candidates proceed to interviews

---

## AI Powered Interviews

Interview features include:

* Built-in video interviews
* Mandatory screen sharing
* Tab switching detection
* Interview recording
* AI-based interview evaluation
* Automated performance summaries

---

## Mock Interview System

Users can practice interviews using AI.

The system evaluates:

* Communication skills
* Speech confidence
* Technical responses
* Resume understanding
* Overall performance

Outputs include:

* Performance score
* Weakness analysis
* Suggestions for improvement

---

# Recruitment Workflow

```text
User Registration
       ↓
Resume Upload
       ↓
AI Resume Analysis
       ↓
Skill Gap Detection
       ↓
Job Matching
       ↓
AI Assessment Test
       ↓
Interview Process
       ↓
Final Evaluation
```

---

# Match Scoring

RecruitO scores a resume against a job using two independent, explainable
signals. Per-application results are exposed via:

* `GET /applications/{id}/skill-gap` — matched vs. missing required skills.
* `GET /applications/{id}/semantic-match` — embedding-based similarity.

## 1. ATS Match Score (rule-based, unchanged)

`backend/app/services/resume_parser.py::compute_match_score` returns a 0-100
score as a weighted combination of two fixed components:

```text
skill_component    = (matched required skills / total required skills) * 70
keyword_component  = (matched description keywords / total description keywords) * 30
match_score        = round(skill_component + keyword_component)         # 0-100
```

When a job has no explicit skill list, the skill component is derived from
known skills in the resume that also appear in the job description (capped at
70). Matching is case-insensitive and tolerant to punctuation/hyphenation
variants via the shared skill vocabulary.

## 2. Semantic Match Score (embedding-based, independent)

`backend/app/services/semantic_matcher.py::compute_semantic_score` uses a
Sentence Transformer model (`all-MiniLM-L6-v2`, local — no external LLM/API) to
encode the resume text and the job description and compare them with cosine
similarity:

```text
embed_resume = SentenceTransformer(resume_text)
embed_job    = SentenceTransformer(job_description)
cosine       = dot(normalize(embed_resume), normalize(embed_job))   # clamped to [0, 1]
semantic_score = round(cosine * 100)                                # 0-100
```

The semantic score is returned **alongside** the ATS score and never modifies
it. If the model cannot be loaded (offline / first-run), the service falls back
to a deterministic hashed term-frequency embedding so the pipeline still works.
Skill-gap analysis keeps using the rule-based skill matching described in task 1.

---

# AI Career Recommendations

`GET /applications/{id}/career-recommendations` produces a personalized career
plan for a candidate against a target job:

```text
Resume + Target Job
        ↓
matched skills + missing skills   (from the skill-gap analyzer, unchanged)
        ↓
LLM (backend-only)
        ↓
structured, Pydantic-validated JSON plan
```

The plan includes **priority skills to learn**, an **explanation for each skill
gap**, a **suggested learning path**, **relevant project ideas**, and **resume
improvement suggestions**. It is grounded in the existing signals: the matched
and missing skills from `analyze_skill_gap`, the stored ATS `match_score`, and
a freshly computed `semantic_score`.

## Configuring the LLM (required for AI-generated plans)

Add the backend-only API key to `backend/.env` (copy `.env.example`):

```dotenv
LLM_API_KEY=sk-your-backend-only-api-key
LLM_BASE_URL=https://api.openai.com/v1   # any OpenAI-compatible endpoint
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT=60
```

The key is read exclusively from the backend environment and is **never
exposed to the frontend**: the browser only talks to our `/applications/...`
endpoints, which return the validated plan (which never contains the key). The
client is provider-agnostic (OpenAI, Azure OpenAI, OpenRouter, local servers).

## Graceful degradation

If `LLM_API_KEY` is unset, the provider errors, or the response cannot be
parsed into the expected structure, the endpoint does **not** fail: it returns
deterministic rule-based recommendations derived from the skill-gap analysis,
with `generated_by="fallback"` and a `notice` explaining why. A successful LLM
call returns `generated_by="llm"`. No RAG/retrieval is used yet; all context is
provided inline in the prompt.

---

# Technology Stack

## Frontend

* React
* TypeScript
* Tailwind CSS

## Backend

* FastAPI
* Python

## Database

* PostgreSQL / MongoDB

## AI Components

* Resume Parsing
* NLP Models
* Recommendation Engine
* Generative AI
* Skill Matching System

## Authentication

* JWT Authentication

---

# Future Scope

* Real-time AI career mentor
* Multi-language support
* Advanced fraud detection
* Recruiter assistance tools
* Enterprise hiring solutions

---

# Project Goal

RecruitO aims to create an intelligent recruitment ecosystem where AI supports candidates throughout their career journey—from skill development to successful recruitment.

---

# Contributors

* Rutuja Pathak
* Shrey Ruparel

---

# License

This project is created for educational and learning purposes.
