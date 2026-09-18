import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { useAuthStore } from "../../store/AuthStore";
import { api } from "../../lib/api";

type Role = "user" | "company";

export default function Signup() {
  const navigate = useNavigate();
  const login = useAuthStore((state) => state.login);
  const [role, setRole] = useState<Role>("user");

  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const [fullName, setFullName] = useState("");

  const [companyName, setCompanyName] = useState("");
  const [website, setWebsite] = useState("");
  const [registrationNumber, setRegistrationNumber] = useState("");
  const [industry, setIndustry] = useState("");

  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  const isCandidate = role === "user";

  const isFreeEmail = (email: string) => {
    return /@(gmail|yahoo|outlook|hotmail)\.com$/i.test(email);
  };

  const handleEmailChange = (value: string) => {
    setEmail(value);
    if (otpSent) {
      // A code is bound to the email it was sent to; require a fresh OTP.
      setOtpSent(false);
      setOtp("");
      setSuccess("");
    }
  };

  const switchRole = (next: Role) => {
    setRole(next);
    setOtp("");
    setOtpSent(false);
    setSuccess("");
    setError("");
  };

  const sendVerificationCode = async () => {
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      await api.post("/send-otp", { email });
      setOtpSent(true);
      setSuccess(
        `Verification code sent to ${email}. Check your inbox and enter the 6-digit code below.`
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to send verification code. Please try again."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (!email || !phone || !password || !confirmPassword) {
      setError("All required fields must be filled");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (password.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }

    if (isCandidate) {
      if (!fullName) {
        setError("Please complete all candidate fields");
        return;
      }
    }

    if (role === "company") {
      if (!companyName || !website || !registrationNumber || !industry) {
        setError("All company fields are required");
        return;
      }

      if (isFreeEmail(email)) {
        setError("Use official company email (no Gmail/Yahoo)");
        return;
      }
    }

    // Candidate signup requires OTP verification: send the code first, then
    // block submission until a code has actually been provided.
    if (isCandidate && !otpSent) {
      await sendVerificationCode();
      return;
    }

    if (isCandidate && (!otp || otp.trim().length !== 6)) {
      setError("Enter the 6-digit verification code sent to your email.");
      return;
    }

    setLoading(true);
    try {
      await api.post("/signup", {
        name: isCandidate ? fullName : companyName,
        email,
        phone,
        password,
        role,
        otp: isCandidate ? otp.trim() : "",
      });

      // Auto-login after successful signup
      try {
        const loginData = await api.post<{
          access_token: string;
          role: string;
          name: string;
        }>("/login", { email, password });

        login(loginData.access_token, loginData.role as "admin" | "company" | "user", loginData.name, email);

        if (role === "company" && loginData.access_token) {
          await api
            .post("/companies", {
              name: companyName,
              website,
              registration_number: registrationNumber,
              industry,
            })
            .catch(() => {});
        }
      } catch {
        // Token issuance failure is non-fatal
      }

      setSuccess("Account created successfully. Redirecting...");

      if (isCandidate) {
        navigate("/dashboard");
      } else {
        navigate("/company/dashboard");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Server error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f172a] via-[#111827] to-[#0a0f1f] px-4">
      <motion.div
        initial={{ opacity: 0, y: 25 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="w-full max-w-lg backdrop-blur-xl bg-white/5 border border-white/10 rounded-3xl p-10 shadow-2xl"
      >
        <h1 className="text-4xl font-bold text-white text-center">
          Create your account
        </h1>

        {/* Toggle */}
        <div className="flex justify-center mt-8">
          <div className="relative bg-white/10 p-1 rounded-full flex w-72">
            <motion.div
              layout
              transition={{ type: "spring", stiffness: 500, damping: 30 }}
              className="absolute top-1 bottom-1 w-1/2 rounded-full bg-gradient-to-r from-violet-600 to-blue-600"
              style={{ left: role === "user" ? "4px" : "50%" }}
            />

            <button
              type="button"
              onClick={() => switchRole("user")}
              className={`relative z-10 w-1/2 py-2 text-sm ${
                role === "user" ? "text-white" : "text-white/70"
              }`}
            >
              Candidate
            </button>

            <button
              type="button"
              onClick={() => switchRole("company")}
              className={`relative z-10 w-1/2 py-2 text-sm ${
                role === "company" ? "text-white" : "text-white/70"
              }`}
            >
              Company
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="mt-10 space-y-6">

          <AnimatePresence mode="wait">
            {role === "user" && (
              <motion.div
                key="candidate"
                initial={{ opacity: 0, x: -40 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 40 }}
                transition={{ duration: 0.35 }}
                className="space-y-6"
              >
                <input
                  placeholder="Full Name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="inputStyle"
                />

                <input
                  type="email"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => handleEmailChange(e.target.value)}
                  className="inputStyle"
                />
              </motion.div>
            )}

            {role === "company" && (
              <motion.div
                key="company"
                initial={{ opacity: 0, x: 40 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -40 }}
                transition={{ duration: 0.35 }}
                className="space-y-6"
              >
                <input placeholder="Company Name" value={companyName}
                  onChange={(e)=>setCompanyName(e.target.value)} className="inputStyle"/>

                <input type="email" placeholder="Official Company Email"
                  value={email} onChange={(e)=>handleEmailChange(e.target.value)}
                  className="inputStyle"/>

                <input placeholder="Company Website" value={website}
                  onChange={(e)=>setWebsite(e.target.value)} className="inputStyle"/>

                <input placeholder="Registration Number"
                  value={registrationNumber}
                  onChange={(e)=>setRegistrationNumber(e.target.value)}
                  className="inputStyle"/>

                <input placeholder="Industry" value={industry}
                  onChange={(e)=>setIndustry(e.target.value)} className="inputStyle"/>
              </motion.div>
            )}
          </AnimatePresence>

          <input placeholder="Phone Number" value={phone}
            onChange={(e)=>setPhone(e.target.value)} className="inputStyle"/>

          <input type="password" placeholder="Password"
            value={password} onChange={(e)=>setPassword(e.target.value)}
            className="inputStyle"/>

          <input type="password" placeholder="Confirm Password"
            value={confirmPassword}
            onChange={(e)=>setConfirmPassword(e.target.value)}
            className="inputStyle"/>

          {isCandidate && otpSent && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="space-y-2"
            >
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                placeholder="6-digit verification code"
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                className="inputStyle tracking-[0.3em] text-center"
              />
              <button
                type="button"
                onClick={sendVerificationCode}
                disabled={loading}
                className="text-violet-400 text-sm hover:text-violet-300 disabled:opacity-50"
              >
                Resend code
              </button>
            </motion.div>
          )}

          {error && (
            <p className="text-red-400 text-sm text-center">{error}</p>
          )}
          {success && (
            <p className="text-emerald-400 text-sm text-center">{success}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-4 rounded-full bg-gradient-to-r from-violet-600 to-blue-600 text-white font-semibold hover:scale-105 disabled:opacity-60 disabled:hover:scale-100"
          >
            {loading
              ? isCandidate && !otpSent
                ? "Sending code..."
                : "Creating account..."
              : isCandidate && !otpSent
              ? "Send Verification Code"
              : "Sign Up"}
          </button>

        </form>

        <p className="text-center text-white/60 mt-8">
          Already have an account?{" "}
          <Link to="/signin" className="text-violet-400">
            Sign In
          </Link>
        </p>
      </motion.div>

      <style>{`
      .inputStyle {
        width: 100%;
        padding: 12px 20px;
        border-radius: 14px;
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        color: white;
        outline: none;
      }
      `}</style>
    </section>
  );
}