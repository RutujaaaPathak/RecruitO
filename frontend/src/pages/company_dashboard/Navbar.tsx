import { Sun, Moon, User } from "lucide-react";
import useTheme from "./hooks/useTheme";
import { useNavigate } from "react-router-dom";
import NotificationsBell from "../../components/NotificationsBell";

export default function Navbar(): JSX.Element {
  const { theme, setTheme } = useTheme();
  const navigate = useNavigate();

  return (
    <div
      className="
        h-20 px-8
        flex items-center justify-between
        bg-white dark:bg-gray-900
        border-b border-gray-200 dark:border-gray-800
        shadow-sm
        transition-colors duration-300
      "
    >
      {/* Left Section - Title */}
      <div className="flex items-center gap-4">
        {/* Accent Line */}
        <div className="w-1.5 h-10 bg-indigo-600 rounded-full" />

        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">
            Company Dashboard
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Overview & hiring insights
          </p>
        </div>
      </div>

      {/* Right Section - Controls */}
      <div
        className="
          flex items-center gap-3
          bg-gray-100 dark:bg-gray-800
          px-4 py-2
          rounded-xl
          transition-colors duration-300
        "
      >
        {/* Theme Toggle */}
        <button
          onClick={() =>
            setTheme(theme === "dark" ? "light" : "dark")
          }
          className="
            p-2 rounded-lg
            bg-white dark:bg-gray-700
            text-gray-800 dark:text-gray-200
            hover:scale-105
            transition-all duration-200
            shadow-sm
          "
          title="Toggle theme"
        >
          {theme === "dark" ? (
            <Sun size={18} />
          ) : (
            <Moon size={18} />
          )}
        </button>

        {/* Notifications */}
        <NotificationsBell buttonClassName="hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300" />

        {/* Profile Button */}
        <button
          onClick={() => navigate("/company/profile")}
          className="
            flex items-center gap-2
            px-3 py-2
            bg-white dark:bg-gray-700
            text-gray-800 dark:text-gray-200
            rounded-lg
            hover:scale-105
            transition-all duration-200
            shadow-sm
          "
        >
          <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-white">
            <User size={16} />
          </div>

          <span className="text-sm font-medium">
            Profile
          </span>
        </button>
      </div>
    </div>
  );
}
