import { Routes, Route, Outlet } from "react-router-dom";

import Landing from "./pages/landing/Landing";
import SignIn from "./pages/auth/SignIn";
import Signup from "./pages/auth/Signup";

import DashboardLayout from "./pages/user_dashboard/DashboardLayout";
import DashboardHome from "./pages/user_dashboard/DashboardHome";
import Profile from "./pages/user_dashboard/Profile";
import Jobs from "./pages/user_dashboard/Jobs";
import Internships from "./pages/user_dashboard/Internships";
import Resume from "./pages/user_dashboard/Resume";
import AIChatbot from "./pages/user_dashboard/AIChatbot";
import Settings from "./pages/user_dashboard/Settings";
import Interviews from "./pages/user_dashboard/Interviews";

// Company Imports
import CompanyDashboard from "./pages/company_dashboard/CompanyDashboard";
import Analytics from "./pages/company_dashboard/Analytics";
import Applicants from "./pages/company_dashboard/Applicants";
import CompanyProfile from "./pages/company_dashboard/CompanyProfile";
import JobPostings from "./pages/company_dashboard/JobPostings";
import JobDetail from "./pages/company_dashboard/JobDetail";
import CompanyInterviews from "./pages/company_dashboard/Interview";
import CompanySettings from "./pages/company_dashboard/Settings_company";
import ApplicantDetail from "./pages/company_dashboard/ApplicantDetail";
import { JobsProvider } from "./pages/company_dashboard/JobsContext";

// Admin Imports
import AdminLayout from "./pages/admin_dashboard/AdminLayout";
import AdminHome from "./pages/admin_dashboard/AdminHome";
import ManageUsers from "./pages/admin_dashboard/ManageUsers";
import ManageCompanies from "./pages/admin_dashboard/ManageCompanies";
import ManageJobs from "./pages/admin_dashboard/ManageJobs";
import Applications from "./pages/admin_dashboard/Applications";
import AdminInterviews from "./pages/admin_dashboard/AdminInterviews";
import AIInsights from "./pages/admin_dashboard/AIInsights";
import Reports from "./pages/admin_dashboard/Reports";
import Notifications from "./pages/admin_dashboard/Notifications";
import AdminSettings from "./pages/admin_dashboard/AdminSettings";

// A wrapper to inject JobsProvider context for all company routes
function CompanyRoutesWrapper() {
  return (
    <JobsProvider>
      <Outlet />
    </JobsProvider>
  );
}

function App() {
  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/" element={<Landing />} />
      <Route path="/signin" element={<SignIn />} />
      <Route path="/signup" element={<Signup />} />

      {/* User Dashboard */}
      <Route path="/dashboard" element={<DashboardLayout />}>
        <Route index element={<DashboardHome />} />
        <Route path="profile" element={<Profile />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="internships" element={<Internships />} />
        <Route path="resume" element={<Resume />} />
        <Route path="chatbot" element={<AIChatbot />} />
        <Route path="settings" element={<Settings />} />
        <Route path="interview" element={<Interviews />} />
      </Route>

      {/* Company Dashboard */}
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

      {/* Admin Dashboard */}
      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<AdminHome />} />
        <Route path="users" element={<ManageUsers />} />
        <Route path="companies" element={<ManageCompanies />} />
        <Route path="jobs" element={<ManageJobs />} />
        <Route path="applications" element={<Applications />} />
        <Route path="interviews" element={<AdminInterviews />} />
        <Route path="ai-insights" element={<AIInsights />} />
        <Route path="reports" element={<Reports />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="settings" element={<AdminSettings />} />
      </Route>
    </Routes>
  );
}

export default App;