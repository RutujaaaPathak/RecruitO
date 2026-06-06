import { ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Building2,
  Briefcase,
  Users,
  BarChart3,
  Video,
  Settings,
  LogOut,
} from "lucide-react";
import { useAuthStore } from "../../store/AuthStore";

export default function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const logout = useAuthStore((state) => state.logout);

  return (
    <div
      className="
        h-screen w-64 flex flex-col
        bg-gradient-to-b from-gray-900 via-gray-900 to-black
        text-white
        border-r border-white/10
      "
    >
      {/* Logo */}
      <div className="p-6 text-2xl font-bold tracking-wide text-indigo-400">
        RecruitO<span className="text-white"></span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 space-y-1">
        <Item
          icon={<LayoutDashboard size={18} />}
          label="Dashboard"
          active={location.pathname === "/company/dashboard"}
          onClick={() => navigate("/company/dashboard")}
        />

        <Item
          icon={<Users size={18} />}
          label="Applicants"
          active={location.pathname === "/company/applicants"}
          onClick={() => navigate("/company/applicants")}
        />

        <Item
          icon={<Building2 size={18} />}
          label="Company Profile"
          active={location.pathname === "/company/profile"}
          onClick={() => navigate("/company/profile")}
        />

        <Item
          label="Job Postings"
          icon={<Briefcase size={18} />}
          active={location.pathname === "/company/job-postings"}
          onClick={() => navigate("/company/job-postings")}
        />


        <Item
          icon={<BarChart3 size={18} />}
          label="Analytics"
          active={location.pathname === "/company/analytics"}
          onClick={() => navigate("/company/analytics")}
        />

        <Item
          icon={<Video size={18} />}
          label="Interviews"
          active={location.pathname === "/company/interview"}
          onClick={() => navigate("/company/interview")}
        />

        <Item
          icon={<Settings size={18} />}
          label="Settings"
          active={location.pathname === "/company/setting"}
          onClick={() => navigate("/company/setting")}
        />

        <Item
          icon={<LogOut size={18} />}
          label="Logout"
          onClick={() => {
            logout();
            navigate("/signin");
          }}
        />
      </nav>

      {/* Footer */}
      <div className="p-4 text-xs text-gray-400 border-t border-white/10">
        © 2026 RecruitO
      </div>
    </div>
  );
}

/* ---------- Sidebar Item Component ---------- */

interface ItemProps {
  icon: ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
}

function Item({ icon, label, active = false, onClick }: ItemProps) {
  return (
    <div
      onClick={onClick}
      className={`
        relative flex items-center gap-3 px-4 py-2 rounded-lg cursor-pointer
        transition-all duration-200
        ${
          active
            ? "bg-indigo-600/20 text-white"
            : "text-gray-300 hover:bg-white/10 hover:text-white"
        }
      `}
    >
      {/* Active Indicator */}
      {active && (
        <span className="absolute left-0 h-8 w-1 bg-indigo-500 rounded-r-md" />
      )}

      {icon}
      <span className="text-sm font-medium">{label}</span>
    </div>
  );
}
