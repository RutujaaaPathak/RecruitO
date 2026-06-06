import { useNavigate, NavLink, Outlet } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useAuthStore } from "../../store/AuthStore";

export default function AdminLayout() {
  const navigate = useNavigate();
  const logout = useAuthStore((state) => state.logout);

  const navItems = [
    { name: "Dashboard", path: "/admin" },
    { name: "Users", path: "/admin/users" },
    { name: "Companies", path: "/admin/companies" },
    { name: "Jobs", path: "/admin/jobs" },
    { name: "Applications", path: "/admin/applications" },
    { name: "Interviews", path: "/admin/interviews" },
    { name: "AI Insights", path: "/admin/ai-insights" },
    { name: "Reports", path: "/admin/reports" },
    { name: "Notifications", path: "/admin/notifications" },
    { name: "Settings", path: "/admin/settings" },
  ];

  return (
    <div className="min-h-screen bg-[#0f172a] text-white flex">

      {/* SIDEBAR */}
      <aside className="w-64 bg-[#0b1120] border-r border-white/10 px-6 py-8 flex flex-col">

        <h2 className="text-xl font-semibold mb-10 tracking-wide">
          RecruitO Admin
        </h2>

        <nav className="space-y-2 flex-1">
          {navItems.map((item) => (
            <NavLink
              key={item.name}
              to={item.path}
              end={item.path === "/admin"}
              className={({ isActive }) =>
                `block px-4 py-2 rounded-xl transition ${
                  isActive
                    ? "bg-gradient-to-r from-violet-600 to-blue-600 text-white shadow-md"
                    : "text-white/70 hover:bg-white/5 hover:text-white"
                }`
              }
            >
              {item.name}
            </NavLink>
          ))}
        </nav>

        <Button
          variant="destructive"
          className="mt-6 rounded-xl"
          onClick={() => {
            logout();
            navigate("/signin");
          }}
        >
          Logout
        </Button>
      </aside>

      {/* MAIN AREA */}
      <div className="flex-1 flex flex-col">

        <div className="flex justify-between items-center px-10 py-6 border-b border-white/10 bg-[#111827]">
          <h1 className="text-2xl font-semibold">
            Admin Dashboard
          </h1>

          <Avatar className="cursor-pointer hover:scale-105 transition">
            <AvatarFallback>AD</AvatarFallback>
          </Avatar>
        </div>

        <div className="flex-1 px-10 py-10 bg-gradient-to-b from-[#111827] to-[#0f172a]">
          <Outlet />
        </div>
      </div>
    </div>
  );
}