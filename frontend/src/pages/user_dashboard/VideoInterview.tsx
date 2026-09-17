import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Camera,
  CameraOff,
  Clock,
  History,
  Loader2,
  Mic,
  MicOff,
  Play,
  Send,
  Sparkles,
  Video,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api } from "../../lib/api";

// ---------------------------------------------------------------------------
// Backend response shapes (mirror backend/app/schemas.py)
// ---------------------------------------------------------------------------

type VideoInterviewStatus = "in_progress" | "completed";

interface ChunkSource {
  chunk_id: number;
  chunk_index: number;
  section: string | null;
  score: number | null;
  content: string;
}

interface VideoInterviewQuestionOut {
  id: number;
  question_index: number;
  category: string;
  question_text: string;
  generated_by: "llm" | "fallback";
  notice: string | null;
  sources: ChunkSource[];
}

interface EvaluationOut {
  score: number;
  correctness: string;
  strengths: string[];
  weaknesses: string[];
  missing_points: string[];
  feedback: string;
  generated_by: "llm" | "fallback";
  notice: string | null;
}

interface AnsweredVideoQuestionOut {
  question: VideoInterviewQuestionOut;
  answer: string;
  evaluation: EvaluationOut;
}

interface VideoInterviewListOut {
  id: number;
  application_id: number;
  job_title: string | null;
  company_name: string | null;
  status: VideoInterviewStatus;
  camera_enabled: boolean;
  microphone_enabled: boolean;
  started_at: string;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
}

interface VideoInterviewDetailOut extends VideoInterviewListOut {
  user_id: number;
  max_questions: number;
  answered_count: number;
  current_question: VideoInterviewQuestionOut | null;
  answered: AnsweredVideoQuestionOut[];
}

interface VideoInterviewAnswerResponse {
  session: VideoInterviewDetailOut;
  evaluation: EvaluationOut;
  next_question: VideoInterviewQuestionOut | null;
}

interface ApplicationData {
  id: number;
  job_id: number;
  status: string;
  match_score: number | null;
  created_at: string;
  job_title: string | null;
  company_name: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function stopTracks(stream: MediaStream | null): void {
  if (!stream) return;
  stream.getTracks().forEach((t) => t.stop());
}

function errMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

function mediaErr(e: unknown): string {
  if (e && typeof e === "object" && "name" in e) {
    const name = (e as DOMException).name;
    if (name === "NotAllowedError" || name === "SecurityError") {
      return "Camera/mic access is blocked. Allow permissions for this site and retry.";
    }
    if (name === "NotFoundError") return "No camera or microphone found.";
  }
  return errMessage(e, "Could not access your camera or microphone.");
}

function elapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m + ":" + String(s).padStart(2, "0");
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function scoreColor(score: number): string {
  if (score >= 8) return "text-green-400";
  if (score >= 5) return "text-yellow-400";
  return "text-red-400";
}

const CATEGORY_LABELS: Record<string, string> = {
  technical: "Technical",
  project_experience: "Project Experience",
  problem_solving: "Problem Solving",
  behavioral: "Behavioral",
};

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type View = "loading" | "home" | "room";

export default function VideoInterview() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [cameraOn, setCameraOn] = useState(true);
  const [micOn, setMicOn] = useState(true);
  const [view, setView] = useState<View>("loading");

  const [apps, setApps] = useState<ApplicationData[]>([]);
  const [sessions, setSessions] = useState<VideoInterviewListOut[]>([]);
  const [active, setActive] = useState<VideoInterviewDetailOut | null>(null);

  const [initError, setInitError] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [startingId, setStartingId] = useState<number | null>(null);
  const [resumingId, setResumingId] = useState<number | null>(null);
  const [ending, setEnding] = useState(false);

  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [evaluation, setEvaluation] = useState<EvaluationOut | null>(null);

  const [now, setNow] = useState<number>(Date.now());

  useEffect(() => {
    return () => stopTracks(streamRef.current);
  }, []);

  // -------------------------------------------------------------------------
  // Media helpers
  // -------------------------------------------------------------------------

  const requestStream = useCallback(async (): Promise<MediaStream> => {
    return navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user" },
      audio: true,
    });
  }, []);

  const attachStream = useCallback(async (s: MediaStream): Promise<void> => {
    streamRef.current = s;
    setStream(s);
    if (videoRef.current) {
      videoRef.current.srcObject = s;
      await videoRef.current.play().catch(() => undefined);
    }
  }, []);

  const detachStream = useCallback((): void => {
    stopTracks(streamRef.current);
    streamRef.current = null;
    setStream(null);
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const applyState = useCallback((s: MediaStream, cam: boolean, mic: boolean) => {
    s.getVideoTracks().forEach((t) => {
      t.enabled = cam;
    });
    s.getAudioTracks().forEach((t) => {
      t.enabled = mic;
    });
  }, []);

  // -------------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------------

  const enterRoom = useCallback(
    async (session: VideoInterviewDetailOut): Promise<void> => {
      setActive(session);
      setCameraOn(session.camera_enabled);
      setMicOn(session.microphone_enabled);
      setAnswer("");
      setEvaluation(null);
      setErr(null);
      setNow(Date.now());
      setView("room");
      try {
        const s = await requestStream();
        await attachStream(s);
        applyState(s, session.camera_enabled, session.microphone_enabled);
      } catch (e) {
        setErr(mediaErr(e));
      }
    },
    [requestStream, attachStream, applyState]
  );

  // Initial load: applications + sessions. If a video interview is already in
  // progress, resume the room (fetching the fresh session detail with its
  // current question) so a page refresh picks it back up.
  useEffect(() => {
    let cancelled = false;

    const init = async (): Promise<void> => {
      setInitError(null);
      try {
        const [appsData, sessionsData] = await Promise.all([
          api.get<ApplicationData[]>("/applications"),
          api.get<VideoInterviewListOut[]>("/video-interviews"),
        ]);
        if (cancelled) return;
        setApps(appsData);
        setSessions(sessionsData);

        const inProgress = sessionsData.find(
          (s) => s.status === "in_progress"
        );
        if (inProgress) {
          const data = await api.get<VideoInterviewDetailOut>(
            `/video-interviews/${inProgress.id}`
          );
          if (cancelled) return;
          await enterRoom(data);
          return;
        }
        setView("home");
      } catch (e) {
        if (!cancelled) {
          setInitError(errMessage(e, "Failed to load video interview data"));
          setView("home");
        }
      }
    };

    void init();
    return () => {
      cancelled = true;
    };
  }, [enterRoom]);

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  const startInterview = async (appId: number): Promise<void> => {
    setStartingId(appId);
    setErr(null);
    let acquired: MediaStream | null = null;
    try {
      // Grab the device streams first (the click is a user gesture, so the
      // permission prompt is allowed) and report the live state on creation.
      acquired = await requestStream().catch(() => null);
      const created = await api.post<VideoInterviewDetailOut>(
        "/video-interviews",
        {
          application_id: appId,
          camera_enabled: cameraOn,
          microphone_enabled: micOn,
        }
      );
      setActive(created);
      setCameraOn(created.camera_enabled);
      setMicOn(created.microphone_enabled);
      setAnswer("");
      setEvaluation(null);
      setSessions((prev) => [created, ...prev.filter((s) => s.id !== created.id)]);
      if (acquired) {
        await attachStream(acquired);
        applyState(acquired, created.camera_enabled, created.microphone_enabled);
      }
      setNow(Date.now());
      setView("room");
    } catch (e) {
      if (acquired) detachStream();
      const message = errMessage(e, "Failed to start the video interview");
      // The backend refuses to start a second session for the same application
      // (409). If one is already live for this application, resume it instead.
      try {
        const data = await api.get<VideoInterviewListOut[]>("/video-interviews");
        setSessions(data);
        const inProgress = data.find(
          (s) => s.status === "in_progress" && s.application_id === appId
        );
        if (inProgress) {
          const detail = await api.get<VideoInterviewDetailOut>(
            `/video-interviews/${inProgress.id}`
          );
          await enterRoom(detail);
          return;
        }
      } catch {
        // Fall through and surface the original error.
      }
      setErr(message);
    } finally {
      setStartingId(null);
    }
  };

  const resumeInterview = async (id: number): Promise<void> => {
    setResumingId(id);
    setErr(null);
    try {
      const data = await api.get<VideoInterviewDetailOut>(
        `/video-interviews/${id}`
      );
      await enterRoom(data);
    } catch (e) {
      setErr(errMessage(e, "Failed to resume the video interview"));
    } finally {
      setResumingId(null);
    }
  };

  const submitAnswer = async (): Promise<void> => {
    const current = active?.current_question;
    const text = answer.trim();
    if (!active || !current || submitting || text.length === 0) return;
    setSubmitting(true);
    setErr(null);
    try {
      const res = await api.post<VideoInterviewAnswerResponse>(
        `/video-interviews/${active.id}/answer`,
        { answer_text: text }
      );
      setEvaluation(res.evaluation);
      setAnswer("");
      setActive(res.session);
      setSessions((prev) =>
        prev.map((s) => (s.id === res.session.id ? res.session : s))
      );
    } catch (e) {
      setErr(errMessage(e, "Failed to submit your answer"));
    } finally {
      setSubmitting(false);
    }
  };

  const endInterview = async (): Promise<void> => {
    if (!active || ending) return;
    setEnding(true);
    setErr(null);
    const sessionId = active.id;
    try {
      const ended = await api.post<VideoInterviewDetailOut>(
        `/video-interviews/${sessionId}/end`
      );
      detachStream();
      setActive(null);
      setAnswer("");
      setEvaluation(null);
      setSessions((prev) => [ended, ...prev.filter((s) => s.id !== ended.id)]);
      setView("home");
    } catch (e) {
      setErr(
        errMessage(e, "Failed to end the interview. The session is still live.")
      );
    } finally {
      setEnding(false);
    }
  };

  const syncDeviceState = useCallback(
    async (cam: boolean, mic: boolean): Promise<void> => {
      if (!active) return;
      try {
        const upd = await api.post<VideoInterviewDetailOut>(
          `/video-interviews/${active.id}/device-state`,
          { camera_enabled: cam, microphone_enabled: mic }
        );
        setActive(upd);
        setSessions((prev) =>
          prev.map((s) => (s.id === upd.id ? upd : s))
        );
      } catch (e) {
        setErr(errMessage(e, "Could not sync your camera/mic state."));
      }
    },
    [active]
  );

  const toggleMic = useCallback(() => {
    const s = streamRef.current;
    if (!s || !active) return;
    const next = !micOn;
    s.getAudioTracks().forEach((t) => {
      t.enabled = next;
    });
    setMicOn(next);
    void syncDeviceState(cameraOn, next);
  }, [micOn, cameraOn, active, syncDeviceState]);

  const toggleCam = useCallback(() => {
    const s = streamRef.current;
    if (!s || !active) return;
    const next = !cameraOn;
    s.getVideoTracks().forEach((t) => {
      t.enabled = next;
    });
    setCameraOn(next);
    void syncDeviceState(next, micOn);
  }, [cameraOn, micOn, active, syncDeviceState]);

  // -------------------------------------------------------------------------
  // Derived state
  // -------------------------------------------------------------------------

  const running = view === "room" && active !== null;

  const inProgressSessions = sessions.filter(
    (s) => s.status === "in_progress"
  );
  const completedSessions = sessions.filter(
    (s) => s.status === "completed"
  );

  const startedMs = active ? new Date(active.started_at).getTime() : 0;
  const timerSeconds =
    active && Number.isFinite(startedMs)
      ? Math.max(0, Math.floor((now - startedMs) / 1000))
      : 0;

  const currentQuestion = active?.current_question ?? null;
  const answeredCount = active?.answered_count ?? 0;
  const maxQuestions = active?.max_questions ?? 0;
  const questionProgress =
    maxQuestions > 0 ? (answeredCount / maxQuestions) * 100 : 0;
  const lastEvaluation: EvaluationOut | null =
    evaluation !== null
      ? evaluation
      : active && active.answered.length > 0
        ? active.answered[active.answered.length - 1].evaluation
        : null;

  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [running]);

  // -------------------------------------------------------------------------
  // Render helpers
  // -------------------------------------------------------------------------

  const ErrorBanner = ({ message }: { message: string }) => (
    <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
      {message}
    </div>
  );

  // -------------------------------------------------------------------------
  // Home screen
  // -------------------------------------------------------------------------

  const renderHome = () => (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold flex items-center gap-3">
            <Video size={32} className="text-violet-400" />
            Technical Video Interview
          </h1>
          <p className="text-white/50 mt-2">
            Run a live camera + microphone interview for the roles you've
            applied to. Your session is saved so you can resume later.
          </p>
        </div>
      </div>

      {initError && <ErrorBanner message={initError} />}
      {err && <ErrorBanner message={err} />}

      {/* ACTIVE SESSIONS */}
      {inProgressSessions.length > 0 && (
        <div className="p-6 rounded-3xl bg-gradient-to-r from-violet-900/30 to-blue-800/20 border border-white/10 shadow-2xl">
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            <Clock size={18} className="text-violet-300" /> In progress
          </h2>
          <div className="space-y-3">
            {inProgressSessions.map((s) => (
              <div
                key={s.id}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">{s.job_title || "Role"}</p>
                  <p className="text-white/50 text-sm">
                    {s.company_name || "Company"}
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    started {formatDate(s.started_at)}
                  </p>
                </div>
                <Button
                  onClick={() => void resumeInterview(s.id)}
                  disabled={resumingId === s.id}
                  className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
                >
                  {resumingId === s.id ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Play size={16} />
                  )}
                  Resume
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* APPLICATIONS */}
      <div>
        <h2 className="text-2xl font-semibold mb-4">Pick an application</h2>
        {apps.length === 0 ? (
          <p className="text-white/50">
            You don't have any applications yet. Apply to a job first so you
            can start a video interview for it.
          </p>
        ) : (
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-5">
            {apps.map((app, index) => {
              const inProgress = sessions.find(
                (s) =>
                  s.status === "in_progress" && s.application_id === app.id
              );
              const isStarting = startingId === app.id;
              return (
                <motion.div
                  key={app.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className="p-6 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 transition flex flex-col gap-3"
                >
                  <div>
                    <h3 className="text-lg font-semibold">
                      {app.job_title || "Role"}
                    </h3>
                    <p className="text-white/60 text-sm">
                      {app.company_name || "Company"}
                    </p>
                    <p className="text-white/40 text-xs mt-1">
                      Applied {formatDate(app.created_at)}
                      {app.match_score != null
                        ? ` • ATS ${app.match_score}%`
                        : ""}
                    </p>
                  </div>
                  {inProgress ? (
                    <div className="flex items-center justify-between mt-auto">
                      <span className="text-xs text-violet-300 flex items-center gap-1.5">
                        <Clock size={12} /> In progress
                      </span>
                      <Button
                        size="sm"
                        onClick={() => void resumeInterview(inProgress.id)}
                        disabled={resumingId === inProgress.id}
                        className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
                      >
                        {resumingId === inProgress.id ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          <Play size={14} />
                        )}
                        Resume
                      </Button>
                    </div>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() => void startInterview(app.id)}
                      disabled={isStarting}
                      className="bg-gradient-to-r from-violet-600 to-blue-600 text-white mt-auto"
                    >
                      {isStarting ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <Play size={14} />
                      )}
                      Start Video Interview
                    </Button>
                  )}
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* PAST SESSIONS */}
      <div>
        <h2 className="text-2xl font-semibold mb-4 flex items-center gap-2">
          <History size={18} className="text-white/40" /> Previous sessions
        </h2>
        {completedSessions.length === 0 ? (
          <p className="text-white/50">
            No completed video interviews yet. Your sessions will appear here.
          </p>
        ) : (
          <div className="space-y-3">
            {completedSessions.map((s) => (
              <motion.div
                key={s.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="p-5 rounded-2xl bg-white/5 border border-white/10 flex flex-wrap items-center justify-between gap-4"
              >
                <div>
                  <p className="font-semibold">
                    {s.job_title || "Role"}
                    <span className="ml-2 text-white/40 text-sm font-normal">
                      {s.company_name || "Company"}
                    </span>
                  </p>
                  <p className="text-white/40 text-xs mt-1">
                    ran {formatDate(s.started_at)}
                    {s.ended_at ? ` • ended ${formatDate(s.ended_at)}` : ""}{" "}
                    • completed
                  </p>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  // -------------------------------------------------------------------------
  // Live room
  // -------------------------------------------------------------------------

  const renderRoom = () => (
    <div className="space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">
            Live Technical Interview
          </h1>
          <p className="text-sm text-white/50">
            {active?.job_title || "Role"}
            {active?.company_name ? ` • ${active.company_name}` : ""} ·{" "}
            {elapsed(timerSeconds)}
          </p>
        </div>
        <span className="flex items-center gap-2 rounded-full bg-red-500/10 px-3 py-1 text-xs font-medium text-red-400">
          <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" />
          LIVE
        </span>
      </header>

      {err && <ErrorBanner message={err} />}

      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-black">
        {cameraOn ? (
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className="aspect-video w-full object-cover"
          />
        ) : (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 bg-gradient-to-br from-violet-950 to-slate-950 text-white/40">
            <CameraOff className="h-12 w-12" />
            <p className="text-sm">Camera is off</p>
          </div>
        )}

        {!stream && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-xs text-white/40">
              Camera unavailable — check your device permissions.
            </p>
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={toggleMic}
          disabled={!stream}
          className="inline-flex items-center gap-2 rounded-xl bg-white/10 px-4 py-2 text-sm font-medium text-white transition hover:bg-white/20 disabled:opacity-50"
        >
          {micOn ? <Mic className="h-4 w-4" /> : <MicOff className="h-4 w-4" />}
          {micOn ? "Mute" : "Unmute"}
        </button>
        <button
          type="button"
          onClick={toggleCam}
          disabled={!stream}
          className="inline-flex items-center gap-2 rounded-xl bg-white/10 px-4 py-2 text-sm font-medium text-white transition hover:bg-white/20 disabled:opacity-50"
        >
          {cameraOn ? (
            <Camera className="h-4 w-4" />
          ) : (
            <CameraOff className="h-4 w-4" />
          )}
          {cameraOn ? "Camera on" : "Camera off"}
        </button>
      </div>

      {/* ---- Question & answer ---- */}
      {currentQuestion && (
        <div className="space-y-4 rounded-2xl border border-white/10 bg-white/5 p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Sparkles size={14} className="text-violet-400" />
              <span className="text-xs uppercase tracking-wider text-white/40">
                {categoryLabel(currentQuestion.category)}
              </span>
              <span className="text-xs text-white/40">
                Q{answeredCount + 1} of {maxQuestions}
              </span>
            </div>
            {maxQuestions > 0 && (
              <div className="h-1.5 w-28 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-violet-500 to-blue-500 transition-all"
                  style={{ width: `${questionProgress}%` }}
                />
              </div>
            )}
          </div>

          {currentQuestion.generated_by === "fallback" && currentQuestion.notice && (
            <p className="text-yellow-400/80 text-xs">{currentQuestion.notice}</p>
          )}

          <p className="text-sm leading-relaxed text-white/90">
            {currentQuestion.question_text}
          </p>
        </div>
      )}

      {!currentQuestion && answeredCount > 0 && (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5 text-center text-sm text-white/50">
          All {answeredCount} questions answered — click{" "}
          <span className="font-medium text-white/70">End Interview</span> to
          finish.
        </div>
      )}

      {/* ---- Latest evaluation ---- */}
      {lastEvaluation && (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5 space-y-3">
          <p className="text-xs uppercase tracking-wider text-white/40">
            Evaluation
          </p>
          <div className="flex items-center gap-3">
            <span
              className={`text-3xl font-bold ${scoreColor(lastEvaluation.score)}`}
            >
              {lastEvaluation.score}
            </span>
            <span className="text-xs text-white/40">/10</span>
            {lastEvaluation.feedback && (
              <span className="ml-4 flex-1 text-xs text-white/60">
                {lastEvaluation.feedback}
              </span>
            )}
          </div>
          {lastEvaluation.strengths.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wider text-emerald-400/80 mb-1">
                Strengths
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {lastEvaluation.strengths.map((s, i) => (
                  <li
                    key={i}
                    className="rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-[11px] text-emerald-300"
                  >
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {lastEvaluation.weaknesses.length > 0 && (
            <div>
              <p className="text-[11px] uppercase tracking-wider text-red-400/80 mb-1">
                Weaknesses
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {lastEvaluation.weaknesses.map((w, i) => (
                  <li
                    key={i}
                    className="rounded-full bg-red-500/10 border border-red-500/20 px-2 py-0.5 text-[11px] text-red-300"
                  >
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ---- Answer input ---- */}
      {currentQuestion && (
        <div className="space-y-3">
          <Textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Type your answer here..."
            rows={4}
            disabled={submitting}
            className="bg-white/5 border-white/10 text-white placeholder:text-white/30"
          />
          <div className="flex justify-end">
            <Button
              onClick={() => void submitAnswer()}
              disabled={submitting || answer.trim().length === 0}
              className="bg-gradient-to-r from-violet-600 to-blue-600 text-white"
            >
              {submitting ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Send size={14} />
              )}
              Submit Answer
            </Button>
          </div>
        </div>
      )}

      <div className="mt-2 flex items-center justify-center">
        <button
          type="button"
          onClick={() => void endInterview()}
          disabled={ending}
          className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-60"
        >
          {ending && <Loader2 className="h-4 w-4 animate-spin" />}
          End Interview
        </button>
      </div>
    </div>
  );

  // -------------------------------------------------------------------------
  // Render switch
  // -------------------------------------------------------------------------

  if (view === "loading") {
    return (
      <div className="flex items-center gap-3 text-white/60 py-16">
        <Loader2 size={20} className="animate-spin" />
        Loading your video interviews...
      </div>
    );
  }

  switch (view) {
    case "room":
      return renderRoom();
    case "home":
    default:
      return renderHome();
  }
}