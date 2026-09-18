import { lazy, Suspense } from "react";
import { Routes, Route, Outlet } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute";

// Layouts and shared providers stay eager (needed on every dashboard view).
import DashboardLayout from "./pages/user_dashboard/DashboardLayout";
import AdminLayout from "./pages/admin_dashboard/AdminLayout";
import { JobsProvider } from "./pages/company_dashboard/JobsContext";

const Landing = lazy(() => import("./pages/landing/Landing"));
const SignIn = lazy(() => import("./pages/auth/SignIn"));
const Signup = lazy(() => import("./pages/auth/Signup"));

const DashboardHome = lazy(() => import("./pages/user_dashboard/DashboardHome"));
const Profile = lazy(() => import("./pages/user_dashboard/Profile"));
const Jobs = lazy(() => import("./pages/user_dashboard/Jobs"));
const Internships = lazy(() => import("./pages/user_dashboard/Internships"));
const Resume = lazy(() => import("./pages/user_dashboard/Resume"));
const AIChatbot = lazy(() => import("./pages/user_dashboard/AIChatbot"));
const MockInterview = lazy(() => import("./pages/user_dashboard/MockInterview"));
const MCQAssessment = lazy(() => import("./pages/user_dashboard/MCQAssessment"));
const CodingTest = lazy(() => import("./pages/user_dashboard/CodingTest"));
const AptitudeTest = lazy(() => import("./pages/user_dashboard/AptitudeTest"));
const VideoInterview = lazy(() => import("./pages/user_dashboard/VideoInterview"));
const Settings = lazy(() => import("./pages/user_dashboard/Settings"));
const Interviews = lazy(() => import("./pages/user_dashboard/Interviews"));
const UserApplications = lazy(() => import("./pages/user_dashboard/UserApplications"));

const CompanyDashboard = lazy(() => import("./pages/company_dashboard/CompanyDashboard"));
const Analytics = lazy(() => import("./pages/company_dashboard/Analytics"));
const Applicants = lazy(() => import("./pages/company_dashboard/Applicants"));
const CompanyProfile = lazy(() => import("./pages/company_dashboard/CompanyProfile"));
const JobPostings = lazy(() => import("./pages/company_dashboard/JobPostings"));
const JobDetail = lazy(() => import("./pages/company_dashboard/JobDetail"));
const CompanyInterviews = lazy(() => import("./pages/company_dashboard/Interview"));
const CompanySettings = lazy(() => import("./pages/company_dashboard/Settings_company"));
const ApplicantDetail = lazy(() => import("./pages/company_dashboard/ApplicantDetail"));

const AdminHome = lazy(() => import("./pages/admin_dashboard/AdminHome"));
const ManageUsers = lazy(() => import("./pages/admin_dashboard/ManageUsers"));
const ManageCompanies = lazy(() => import("./pages/admin_dashboard/ManageCompanies"));
const ManageJobs = lazy(() => import("./pages/admin_dashboard/ManageJobs"));
const AdminApplications = lazy(() => import("./pages/admin_dashboard/Applications"));
const AdminInterviews = lazy(() => import("./pages/admin_dashboard/AdminInterviews"));
const AIInsights = lazy(() => import("./pages/admin_dashboard/AIInsights"));
const Reports = lazy(() => import("./pages/admin_dashboard/Reports"));
const Notifications = lazy(() => import("./pages/admin_dashboard/Notifications"));
const AdminSettings = lazy(() => import("./pages/admin_dashboard/AdminSettings"));

// A wrapper to inject JobsProvider context for all company routes
function CompanyRoutesWrapper() {
  return (
    <JobsProvider>
      <Outlet />
    </JobsProvider>
  );
}

function PageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center text-gray-400">
      Loading...
    </div>
  );
}

function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        {/* Public Routes */}
        <Route path="/" element={<Landing />} />
        <Route path="/signin" element={<SignIn />} />
        <Route path="/signup" element={<Signup />} />

        {/* User Dashboard Protected */}
        <Route element={<ProtectedRoute allowedRoles={["user"]} />}>
          <Route path="/dashboard" element={<DashboardLayout />}>
            <Route index element={<DashboardHome />} />
            <Route path="profile" element={<Profile />} />
            <Route path="jobs" element={<Jobs />} />
            <Route path="internships" element={<Internships />} />
            <Route path="applications" element={<UserApplications />} />
            <Route path="resume" element={<Resume />} />
            <Route path="chatbot" element={<AIChatbot />} />
            <Route path="mock-interview" element={<MockInterview />} />
            <Route path="mcq-assessment" element={<MCQAssessment />} />
            <Route path="coding-test" element={<CodingTest />} />
            <Route path="aptitude-test" element={<AptitudeTest />} />
            <Route path="video-interview" element={<VideoInterview />} />
            <Route path="settings" element={<Settings />} />
            <Route path="interview" element={<Interviews />} />
          </Route>
        </Route>

        {/* Company Dashboard Protected */}
        <Route element={<ProtectedRoute allowedRoles={["company"]} />}>
          <Route element={<CompanyRoutesWrapper />}>
            <Route path="/company" element={<CompanyDashboard />} />
            <Route path="/company/dashboard" element={<CompanyDashboard />} />
            <Route path="/company/applicants" element={<Applicants />} />
            <Route path="/company/applicants/:id" element={<ApplicantDetail />} />
            <Route path="/company/profile" element={<CompanyProfile />} />
            <Route path="/company/analytics" element={<Analytics />} />
            <Route path="/company/job-postings" element={<JobPostings />} />
            <Route path="/company/job-postings/:id" element={<JobDetail />} />
            <Route path="/company/interview" element={<CompanyInterviews />} />
            <Route path="/company/setting" element={<CompanySettings />} />
          </Route>
        </Route>

        {/* Admin Dashboard Protected */}
        <Route element={<ProtectedRoute allowedRoles={["admin"]} />}>
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<AdminHome />} />
            <Route path="users" element={<ManageUsers />} />
            <Route path="companies" element={<ManageCompanies />} />
            <Route path="jobs" element={<ManageJobs />} />
            <Route path="applications" element={<AdminApplications />} />
            <Route path="interviews" element={<AdminInterviews />} />
            <Route path="ai-insights" element={<AIInsights />} />
            <Route path="reports" element={<Reports />} />
            <Route path="notifications" element={<Notifications />} />
            <Route path="settings" element={<AdminSettings />} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  );
}

export default App;