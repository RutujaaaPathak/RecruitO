import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "../../lib/api";

interface ApplicationData {
  id: number;
  job_id: number;
  status: string;
  match_score: number | null;
  created_at: string;
  job_title: string | null;
  company_name: string | null;
}

interface SkillGapItem {
  skill: string;
  recommendation: string;
}

interface SkillGapReport {
  application_id: number;
  job_id: number;
  job_title: string | null;
  company_name: string | null;
  required_skills: string[];
  matched_skills: string[];
  missing_skills: SkillGapItem[];
  matched_count: number;
  missing_count: number;
  coverage_percent: number;
  summary: string;
}

interface SemanticMatchData {
  application_id: number;
  job_id: number;
  job_title: string | null;
  company_name: string | null;
  candidate_name: string | null;
  match_score: number | null;
  semantic_score: number | null;
  cosine_similarity: number | null;
  embedding_model: string | null;
  used_fallback: boolean;
  explanation: string | null;
}

interface SkillLearningPriority {
  skill: string;
  reason: string;
  priority: "high" | "medium" | "low";
}

interface LearningStep {
  step: string;
  detail: string;
}

interface ProjectIdea {
  title: string;
  description: string;
}

interface CareerRecommendations {
  application_id: number;
  job_id: number;
  job_title: string | null;
  company_name: string | null;
  ats_score: number | null;
  semantic_score: number | null;
  matched_skills: string[];
  missing_skills: string[];
  summary: string;
  priority_skills: SkillLearningPriority[];
  learning_path: LearningStep[];
  project_ideas: ProjectIdea[];
  resume_improvements: string[];
  generated_by: "llm" | "fallback";
  notice: string | null;
}

export default function UserApplications() {
  const [applications, setApplications] = useState<ApplicationData[]>([]);
  const [skipGaps, setSkillGaps] = useState<Record<number, SkillGapReport | null>>({});
  const [gapErrors, setGapErrors] = useState<Record<number, string>>({});
  const [semanticMatches, setSemanticMatches] = useState<Record<number, SemanticMatchData | null>>({});
  const [semanticErrors, setSemanticErrors] = useState<Record<number, string>>({});
  const [recommendations, setRecommendations] = useState<Record<number, CareerRecommendations | null>>({});
  const [recLoading, setRecLoading] = useState<Record<number, boolean>>({});
  const [recErrors, setRecErrors] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ApplicationData[]>("/applications")
      .then(async (apps) => {
        setApplications(apps);
        // Fetch the skill-gap report and semantic score for each application
        // alongside the list; both are independent of the ATS match score.
        const results = await Promise.all(
          apps.map(async (app) => {
            const id = app.id;
            const [gapResult, semanticResult] = await Promise.all([
              api
                .get<SkillGapReport>(`/applications/${id}/skill-gap`)
                .then((report) => ({ report, gapError: null }))
                .catch((e) => ({
                  report: null,
                  gapError: e instanceof Error ? e.message : "No analysis available",
                })),
              api
                .get<SemanticMatchData>(`/applications/${id}/semantic-match`)
                .then((data) => ({ data, semanticError: null }))
                .catch((e) => ({
                  data: null,
                  semanticError:
                    e instanceof Error ? e.message : "No semantic match available",
                })),
            ]);
            return { id, ...gapResult, ...semanticResult };
          })
        );
        const gaps: Record<number, SkillGapReport | null> = {};
        const gapErrs: Record<number, string> = {};
        const sem: Record<number, SemanticMatchData | null> = {};
        const semErrs: Record<number, string> = {};
        results.forEach((r) => {
          gaps[r.id] = r.report;
          if (r.gapError) gapErrs[r.id] = r.gapError;
          sem[r.id] = r.data;
          if (r.semanticError) semErrs[r.id] = r.semanticError;
        });
        setSkillGaps(gaps);
        setGapErrors(gapErrs);
        setSemanticMatches(sem);
        setSemanticErrors(semErrs);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load applications")
      )
      .finally(() => setLoading(false));
  }, []);

  const loadRecommendations = async (appId: number) => {
    if (recLoading[appId] || recommendations[appId]) return;
    setRecLoading((prev) => ({ ...prev, [appId]: true }));
    setRecErrors((prev) => {
      const next = { ...prev };
      delete next[appId];
      return next;
    });
    try {
      const data = await api.get<CareerRecommendations>(
        `/applications/${appId}/career-recommendations`
      );
      setRecommendations((prev) => ({ ...prev, [appId]: data }));
    } catch (e) {
      setRecErrors((prev) => ({
        ...prev,
        [appId]: e instanceof Error ? e.message : "Failed to generate recommendations",
      }));
    } finally {
      setRecLoading((prev) => ({ ...prev, [appId]: false }));
    }
  };

  const scoreColor = (score: number) => {
    if (score >= 80) return "text-green-400";
    if (score >= 60) return "text-yellow-400";
    return "text-red-400";
  };

  const gapColor = (coverage: number) => {
    if (coverage >= 80) return "text-green-400";
    if (coverage >= 50) return "text-yellow-400";
    return "text-orange-400";
  };

  const gapBarColor = (coverage: number) => {
    if (coverage >= 80) return "bg-green-500";
    if (coverage >= 50) return "bg-yellow-500";
    return "bg-orange-500";
  };

  const semanticColor = (score: number) => {
    if (score >= 80) return "text-blue-400";
    if (score >= 50) return "text-cyan-400";
    return "text-red-400";
  };

  return (
    <div className="space-y-8">

      {/* HEADER */}
      <div>
        <h1 className="text-4xl font-bold">My Applications</h1>
        <p className="text-white/50 mt-2">
          Track the roles you've applied for and your ATS match score
        </p>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading && <p className="text-white/50">Loading applications...</p>}

      {!loading && applications.length === 0 && (
        <p className="text-white/50">
          You haven't applied to any jobs yet. Browse jobs to get started.
        </p>
      )}

      {!loading && applications.length > 0 && (
        <div className="grid md:grid-cols-2 gap-6">
          {applications.map((app, index) => {
            const gap = skipGaps[app.id];
            const gapError =
              gapErrors[app.id] ?? (app.match_score == null ? undefined : null);
            const semantic = semanticMatches[app.id];
            const semanticError = semanticErrors[app.id];
            const rec = recommendations[app.id];

            return (
              <motion.div
                key={app.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.05 }}
                className="p-6 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 transition"
              >
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <h2 className="text-xl font-semibold">
                      {app.job_title || "Role"}
                    </h2>
                    <p className="text-white/60 text-sm">
                      {app.company_name || "Company"}
                    </p>
                  </div>

                  <span className="text-xs px-3 py-1 rounded-full bg-white/10 capitalize">
                    {app.status}
                  </span>
                </div>

                <div className="flex items-center justify-between mt-4">
                  <span className="text-white/50 text-sm">
                    Applied{" "}
                    {new Date(app.created_at).toLocaleDateString()}
                  </span>

                  <div className="text-right">
                    <span className="text-white/50 text-sm block">
                      ATS Match
                    </span>
                    <span className={`text-2xl font-bold ${scoreColor(app.match_score ?? 0)}`}>
                      {app.match_score != null ? `${app.match_score}%` : "N/A"}
                    </span>
                    {app.match_score == null && (
                      <p className="text-white/40 text-xs mt-1">
                        Upload a resume to get scored.
                      </p>
                    )}
                  </div>
                </div>

                {app.match_score != null && (
                  <div className="w-full bg-white/10 rounded-full h-2 mt-3">
                    <div
                      className={`h-2 rounded-full transition-all duration-700 ${
                        (app.match_score ?? 0) >= 80
                          ? "bg-green-500"
                          : (app.match_score ?? 0) >= 60
                          ? "bg-yellow-500"
                          : "bg-red-500"
                      }`}
                      style={{ width: `${app.match_score ?? 0}%` }}
                    />
                  </div>
                )}

                {/* SEMANTIC MATCH */}
                {semantic ? (
                  <div className="mt-5 p-4 rounded-xl bg-blue-500/5 border border-blue-500/20">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-semibold text-blue-300">
                        Semantic Match
                      </h3>
                      <span className={`text-lg font-bold ${semanticColor(semantic.semantic_score ?? 0)}`}>
                        {semantic.semantic_score != null ? `${semantic.semantic_score}%` : "N/A"}
                      </span>
                    </div>

                    <div className="w-full bg-white/10 rounded-full h-2 mb-2">
                      <div
                        className={`h-2 rounded-full transition-all duration-700 ${
                          (semantic.semantic_score ?? 0) >= 80
                            ? "bg-blue-500"
                            : (semantic.semantic_score ?? 0) >= 50
                            ? "bg-cyan-500"
                            : "bg-red-500"
                        }`}
                        style={{ width: `${semantic.semantic_score ?? 0}%` }}
                      />
                    </div>

                    <p className="text-white/50 text-xs">
                      {semantic.explanation}
                      {semantic.used_fallback && (
                        <span className="block text-yellow-500/80 mt-1">
                          (Note: semantic model unavailable, local fallback used.)
                        </span>
                      )}
                    </p>
                  </div>
                ) : semanticError ? (
                  <div className="mt-5 p-3 rounded-xl bg-white/5 border border-white/10 text-white/40 text-xs">
                    {semanticError}
                  </div>
                ) : (
                  <div className="mt-5 p-3 rounded-xl bg-white/5 border border-white/10 text-white/40 text-xs">
                    Loading semantic match...
                  </div>
                )}

                {/* SKILL GAP ANALYSIS */}
                {gap ? (
                  <div className="mt-5 p-4 rounded-xl bg-violet-500/5 border border-violet-500/20">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-semibold text-violet-300">
                        Skill Gap Analysis
                      </h3>
                      <span className={`text-lg font-bold ${gapColor(gap.coverage_percent)}`}>
                        {gap.coverage_percent}%
                      </span>
                    </div>

                    <p className="text-white/60 text-xs mb-3">{gap.summary}</p>

                    {/* Coverage bar */}
                    <div className="w-full bg-white/10 rounded-full h-2 mb-4">
                      <div
                        className={`h-2 rounded-full transition-all duration-700 ${gapBarColor(gap.coverage_percent)}`}
                        style={{ width: `${gap.coverage_percent}%` }}
                      />
                    </div>

                    {/* Matched skills */}
                    <div className="mb-3">
                      <p className="text-xs text-green-400 font-medium mb-1">
                        Matched Skills ({gap.matched_count})
                      </p>
                      {gap.matched_skills.length > 0 ? (
                        <div className="flex flex-wrap gap-1.5">
                          {gap.matched_skills.map((skill, i) => (
                            <span
                              key={i}
                              className="px-2.5 py-0.5 text-xs rounded-full bg-green-500/15 text-green-300"
                            >
                              {skill}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="text-white/40 text-xs">
                          No required skills matched yet.
                        </p>
                      )}
                    </div>

                    {/* Missing skills */}
                    {gap.missing_skills.length > 0 && (
                      <div>
                        <p className="text-xs text-orange-400 font-medium mb-1">
                          Missing Skills ({gap.missing_count})
                        </p>
                        <ul className="space-y-1.5">
                          {gap.missing_skills.map((item, i) => (
                            <li
                              key={i}
                              className="text-xs text-white/70 bg-orange-500/10 border border-orange-500/20 rounded-lg px-2.5 py-1.5"
                            >
                              <span className="font-semibold text-orange-300">
                                {item.skill}
                              </span>
                              <span className="block text-white/50 mt-0.5">
                                {item.recommendation}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ) : gapError ? (
                  <div className="mt-5 p-3 rounded-xl bg-white/5 border border-white/10 text-white/50 text-xs">
                    {gapError}
                  </div>
                ) : (
                  <div className="mt-5 p-3 rounded-xl bg-white/5 border border-white/10 text-white/50 text-xs">
                    Loading skill gap analysis...
                  </div>
                )}

                {/* AI CAREER RECOMMENDATIONS */}
                {rec ? (
                  <div className="mt-5 p-4 rounded-xl bg-emerald-500/5 border border-emerald-500/20">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-sm font-semibold text-emerald-300">
                        AI Career Recommendations
                      </h3>
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded-full uppercase tracking-wider ${
                          rec.generated_by === "llm"
                            ? "bg-emerald-500/20 text-emerald-300"
                            : "bg-yellow-500/20 text-yellow-300"
                        }`}
                      >
                        {rec.generated_by === "llm"
                          ? "AI Generated"
                          : "Fallback"}
                      </span>
                    </div>

                    {rec.summary && (
                      <p className="text-white/70 text-xs mb-3">
                        {rec.summary}
                      </p>
                    )}

                    {rec.notice && (
                      <p className="text-yellow-500/80 text-xs mb-3">
                        {rec.notice}
                      </p>
                    )}

                    {/* Priority skills */}
                    {rec.priority_skills.length > 0 && (
                      <div className="mb-3">
                        <p className="text-xs text-emerald-400 font-medium mb-1">
                          Priority Skills to Learn
                        </p>
                        <ul className="space-y-1.5">
                          {rec.priority_skills.map((p: SkillLearningPriority, i: number) => (
                            <li
                              key={i}
                              className="text-xs text-white/70 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-2.5 py-1.5"
                            >
                              <span className="font-semibold text-emerald-300 capitalize">
                                {p.skill}
                              </span>
                              <span className="mx-1.5 text-white/30">•</span>
                              <span className="text-[10px] uppercase text-white/40">
                                {p.priority}
                              </span>
                              <span className="block text-white/50 mt-0.5">
                                {p.reason}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Learning path */}
                    {rec.learning_path.length > 0 && (
                      <div className="mb-3">
                        <p className="text-xs text-emerald-400 font-medium mb-1">
                          Suggested Learning Path
                        </p>
                        <ol className="space-y-1.5">
                          {rec.learning_path.map((step: LearningStep, i: number) => (
                            <li
                              key={i}
                              className="text-xs text-white/70 bg-white/5 border border-white/10 rounded-lg px-2.5 py-1.5"
                            >
                              <span className="font-medium text-white/80">
                                {i + 1}. {step.step}
                              </span>
                              {step.detail && (
                                <span className="block text-white/50 mt-0.5">
                                  {step.detail}
                                </span>
                              )}
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}

                    {/* Project ideas */}
                    {rec.project_ideas.length > 0 && (
                      <div className="mb-3">
                        <p className="text-xs text-emerald-400 font-medium mb-1">
                          Relevant Project Ideas
                        </p>
                        <ul className="space-y-1.5">
                          {rec.project_ideas.map((idea: ProjectIdea, i: number) => (
                            <li
                              key={i}
                              className="text-xs text-white/70 bg-white/5 border border-white/10 rounded-lg px-2.5 py-1.5"
                            >
                              <span className="font-medium text-white/80">
                                {idea.title}
                              </span>
                              {idea.description && (
                                <span className="block text-white/50 mt-0.5">
                                  {idea.description}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Resume improvements */}
                    {rec.resume_improvements.length > 0 && (
                      <div>
                        <p className="text-xs text-emerald-400 font-medium mb-1">
                          Resume Improvement Suggestions
                        </p>
                        <ul className="space-y-1.5">
                          {rec.resume_improvements.map((tip: string, i: number) => (
                            <li
                              key={i}
                              className="text-xs text-white/70 flex gap-1.5"
                            >
                              <span className="text-emerald-400">•</span>
                              <span>{tip}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ) : recLoading[app.id] ? (
                  <div className="mt-5 p-3 rounded-xl bg-white/5 border border-white/10 text-white/50 text-xs">
                    Generating AI career recommendations... this can take a few
                    seconds.
                  </div>
                ) : recErrors[app.id] ? (
                  <div className="mt-5 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
                    {recErrors[app.id]}
                  </div>
                ) : (
                  <button
                    onClick={() => loadRecommendations(app.id)}
                    className="mt-5 w-full px-4 py-2.5 text-sm font-medium rounded-xl bg-emerald-600/20 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-600/30 transition"
                  >
                    Get AI Career Recommendations
                  </button>
                )}
              </motion.div>
            );
          })}
        </div>
      )}

    </div>
  );
}
