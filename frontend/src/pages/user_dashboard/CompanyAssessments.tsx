import { ClipboardList } from "lucide-react";

export default function CompanyAssessments() {
  return (
    <div className="space-y-10">
      {/* ================= HEADER ================= */}
      <div>
        <h1 className="text-4xl font-bold">Company Assessments</h1>
        <p className="text-white/50 mt-2 max-w-xl">
          Assessments scheduled by companies as part of your applications will
          appear here.
        </p>
      </div>

      {/* ================= EMPTY STATE ================= */}
      <div className="p-10 md:p-16 rounded-3xl bg-gradient-to-br from-indigo-600/10 to-blue-600/5 border border-white/10 backdrop-blur-xl">
        <div className="flex flex-col items-center text-center gap-4">
          <div className="p-4 rounded-2xl bg-white/10 border border-white/10">
            <ClipboardList
              size={36}
              className="text-indigo-400 group-hover:text-white"
            />
          </div>
          <h2 className="text-xl font-semibold text-white">
            No company assessments yet
          </h2>
          <p className="text-white/50 text-sm max-w-md">
            When a company schedules an assessment for an application you have
            submitted, it will show up here with its deadline and status.
          </p>
          <span className="mt-2 px-4 py-1.5 rounded-full bg-indigo-600/20 text-indigo-300 text-xs font-semibold tracking-wide uppercase">
            Coming soon
          </span>
        </div>
      </div>
    </div>
  );
}