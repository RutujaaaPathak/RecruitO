import { useNavigate, NavLink, Outlet } from "react-router-dom";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useAuthStore } from "../../store/AuthStore";

export default function DashboardLayout() {
  const navigate = useNavigate();
  const logout = useAuthStore((state) => state.logout);
  const name = useAuthStore((state) => state.name);

  // Initials for the avatar, derived from the logged-in user.
  const initials = name
    ? name
        .split(" ")
        .map((part) => part[0])
        .filter(Boolean)
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "U";

  // Apply saved theme on mount
  useEffect(() => {
    const savedTheme = localStorage.getItem("theme");

    if (savedTheme === "light") {
      document.documentElement.classList.remove("dark");
    } else {
      document.documentElement.classList.add("dark");
    }
  }, []);

  const navItems = [
    { name: "Dashboard", path: "/dashboard" },
    { name: "Profile", path: "/dashboard/profile" },
    { name: "Jobs", path: "/dashboard/jobs" },
    { name: "Internships", path: "/dashboard/internships" },
    { name: "Applications", path: "/dashboard/applications" },
    { name: "Interview", path: "/dashboard/interview"},
    { name: "Resume", path: "/dashboard/resume" },
    { name: "AI Chatbot", path: "/dashboard/chatbot" },
    { name: "Mock Interview", path: "/dashboard/mock-interview" },
    { name: "MCQ Assessment", path: "/dashboard/mcq-assessment" },
    { name: "Coding Test", path: "/dashboard/coding-test" },
    { name: "Aptitude Test", path: "/dashboard/aptitude-test" },
    { name: "Video Interview", path: "/dashboard/video-interview" },
    { name: "Settings", path: "/dashboard/settings" },
    
  ];

  return (
    // The user dashboard pages are designed as a dark UI, so the shell always
    // uses a dark background regardless of the saved OS/app theme to keep the
    // inner content readable (fixes invisible text when "light" theme is set).
    <div className="flex min-h-screen bg-[#0f172a] text-white transition-colors duration-300">

      {/* ================= SIDEBAR ================= */}
      <aside className="w-64 bg-[#0b1120] border-r border-white/5 p-6 flex flex-col">

        <h2 className="text-xl font-semibold mb-10 tracking-wide">
          RecruitO
        </h2>

        <nav className="space-y-2 flex-1">
          {navItems.map((item) => (
            <NavLink
              key={item.name}
              to={item.path}
              end={item.path === "/dashboard"}
              className={({ isActive }) =>
                `block px-4 py-2 rounded-lg transition-all ${
                  isActive
                    ? "bg-gradient-to-r from-violet-600 to-blue-600 text-white shadow-lg"
                    : "hover:bg-white/5"
                }`
              }
            >
              {item.name}
            </NavLink>
          ))}
        </nav>

        <Button
          variant="destructive"
          className="w-full mt-6"
          onClick={() => {
            logout();
            navigate("/signin");
          }}
        >
          Logout
        </Button>
      </aside>

      {/* ================= MAIN CONTENT ================= */}
      <div className="flex-1 p-10">

        {/* Top Header */}
        <div className="flex justify-between items-center mb-10">
          <h1 className="text-3xl font-semibold">
            User Dashboard
          </h1>

          {/* Profile Avatar */}
          <Avatar
            className="cursor-pointer hover:scale-105 transition"
            onClick={() => navigate("/dashboard/profile")}
          >
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>
        </div>

        {/* Nested Routes Render Here */}
        <Outlet />
      </div>
    </div>
  );
}