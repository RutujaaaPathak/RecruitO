import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuthStore } from "../../store/AuthStore";

const SignIn = () => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    // Validation
    if (!email || !password) {
      setError("Email and password are required");
      return;
    }

    // Clear error
    setError("");

    try {
      const response = await fetch("http://127.0.0.1:8000/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.detail || "Invalid email or password");
        return;
      }

      // Store in Zustand AuthStore
      login(data.access_token, data.role, data.name, email);

      // Redirect based on role
      if (data.role === "admin") {
        navigate("/admin");
      } else if (data.role === "company") {
        navigate("/company/dashboard");
      } else {
        navigate("/dashboard");
      }
    } catch {
      setError("Failed to connect to the login server. Please make sure the backend is running.");
    }
  };


  return (
    <div
      className="min-h-screen flex items-center justify-center px-4
      bg-gray-50 dark:bg-gradient-to-br dark:from-black dark:via-gray-900 dark:to-black"
    >
      <div
        className="w-full max-w-md rounded-2xl p-8 shadow-xl
        bg-white border border-gray-200
        dark:bg-white/5 dark:border-white/10 dark:backdrop-blur-xl"
      >
        {/* Heading */}
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white text-center">
          Welcome back
        </h1>
        <p className="text-gray-600 dark:text-gray-400 text-center mt-2">
          Sign In to your RecruitO account
        </p>

        {/* Form */}
        <form onSubmit={handleSubmit} className="mt-8 space-y-5">
          {/* Email */}
          <div>
            <label className="block text-sm mb-1 text-gray-700 dark:text-gray-300">
              Email address
            </label>
            <input
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-3 rounded-xl
              bg-white text-gray-900 placeholder-gray-400
              border border-gray-300
              focus:outline-none focus:ring-2 focus:ring-purple-500
              dark:bg-black/40 dark:text-white dark:border-white/10 dark:placeholder-gray-500"
            />
          </div>

          {/* Password */}
          <div>
            <label className="block text-sm mb-1 text-gray-700 dark:text-gray-300">
              Password
            </label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 rounded-xl
              bg-white text-gray-900 placeholder-gray-400
              border border-gray-300
              focus:outline-none focus:ring-2 focus:ring-purple-500
              dark:bg-black/40 dark:text-white dark:border-white/10 dark:placeholder-gray-500"
            />
          </div>

          {/* Forgot password */}
          <div className="flex justify-end">
            <button
              type="button"
              className="text-sm text-purple-600 dark:text-purple-400 hover:underline"
            >
              Forgot password?
            </button>
          </div>

          {/* Error message */}
          {error && (
            <p className="text-sm text-red-500 text-center">
              {error}
            </p>
          )}

          {/* Login button */}
          <button
            type="submit"
            className="w-full py-3 rounded-xl font-semibold text-white
            bg-gradient-to-r from-purple-600 to-blue-600
            hover:opacity-90 transition"
          >
            Sign In
          </button>
        </form>

        {/* Divider */}
        <div className="my-6 flex items-center">
          <div className="flex-1 h-px bg-gray-300 dark:bg-white/10" />
          <span className="px-3 text-sm text-gray-500 dark:text-gray-400">
            OR
          </span>
          <div className="flex-1 h-px bg-gray-300 dark:bg-white/10" />
        </div>

        {/* Signup link */}
        <p className="text-center text-sm text-gray-600 dark:text-gray-400">
          Don’t have an account?{" "}
          <Link
            to="/signup"
            className="text-purple-600 dark:text-purple-400 font-medium hover:underline"
          >
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
};

export default SignIn;
