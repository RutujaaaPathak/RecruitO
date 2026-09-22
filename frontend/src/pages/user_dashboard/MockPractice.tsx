import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight,
  BrainCircuit,
  Code2,
  Cpu,
  Users,
  Video,
} from "lucide-react";

interface PracticeOption {
  key: string;
  title: string;
  description: string;
  route: string;
  icon: typeof BrainCircuit;
  gradient: string;
  iconColor: string;
  glow: string;
}

const options: PracticeOption[] = [
  {
    key: "aptitude",
    title: "Aptitude",
    description:
      "Quantitative, logical and verbal reasoning tests to sharpen your problem-solving speed.",
    route: "/dashboard/aptitude-test",
    icon: BrainCircuit,
    gradient: "from-violet-600/20 to-blue-600/10",
    iconColor: "text-violet-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(139,92,246,0.25)] group-hover:ring-violet-500/30",
  },
  {
    key: "dsa",
    title: "DSA / Coding",
    description:
      "Solve data structures and algorithms problems with real coding tests and instant feedback.",
    route: "/dashboard/coding-test",
    icon: Code2,
    gradient: "from-blue-600/20 to-cyan-500/10",
    iconColor: "text-cyan-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(59,130,246,0.25)] group-hover:ring-blue-400/30",
  },
  {
    key: "technical",
    title: "Technical Round",
    description:
      "AI-generated technical mock interview questions, tailored to your target role.",
    route: "/dashboard/mock-interview",
    icon: Cpu,
    gradient: "from-emerald-600/20 to-teal-500/10",
    iconColor: "text-emerald-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(16,185,129,0.25)] group-hover:ring-emerald-400/30",
  },
  {
    key: "hr",
    title: "HR Interview",
    description:
      "Practice behavioral and HR-style questions to build confidence for the people round.",
    route: "/dashboard/video-interview?type=hr",
    icon: Users,
    gradient: "from-amber-600/20 to-orange-500/10",
    iconColor: "text-amber-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(245,158,11,0.25)] group-hover:ring-amber-400/30",
  },
  {
    key: "video",
    title: "Technical Video Interview",
    description:
      "Record camera-based technical interviews and receive an AI evaluation of your answers.",
    route: "/dashboard/video-interview",
    icon: Video,
    gradient: "from-rose-600/20 to-pink-500/10",
    iconColor: "text-rose-400",
    glow: "group-hover:shadow-[0_20px_60px_rgba(244,63,94,0.25)] group-hover:ring-rose-400/30",
  },
];

export default function MockPractice() {
  const navigate = useNavigate();

  return (
    <div className="space-y-10">
      {/* ================= HEADER ================= */}
      <div>
        <h1 className="text-4xl font-bold">Mock Practice</h1>
        <p className="text-white/50 mt-2 max-w-xl">
          Practice mock tests and interviews in your own time to get ready for
          real assessments.
        </p>
      </div>

      {/* ================= PRACTICE OPTIONS ================= */}
      <div className="grid md:grid-cols-2 gap-6">
        {options.map((option, index) => {
          const Icon = option.icon;
          return (
            <motion.button
              key={option.key}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05 }}
              onClick={() => navigate(option.route)}
              className={`group text-left p-8 rounded-3xl
                bg-gradient-to-br ${option.gradient}
                border border-white/10 backdrop-blur-xl shadow-2xl
                transition-all duration-300 ease-out cursor-pointer
                hover:scale-105 hover:-translate-y-2 ${option.glow}`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="p-3 rounded-2xl bg-white/10 border border-white/10">
                  <Icon size={28} className={option.iconColor} />
                </div>
                <ArrowRight
                  size={20}
                  className="text-white/30 group-hover:text-white/80 group-hover:translate-x-1 transition-all duration-200"
                />
              </div>

              <h2 className="text-xl font-semibold text-white mt-6">
                {option.title}
              </h2>
              <p className="text-white/50 text-sm mt-2 leading-relaxed">
                {option.description}
              </p>

              <p className="text-sm font-semibold mt-4 group-hover:underline decoration-white/40 underline-offset-4">
                <span
                  className={`${option.iconColor} group-hover:text-white transition-colors`}
                >
                  Start practicing
                </span>
              </p>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}