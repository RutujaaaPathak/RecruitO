import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "../store/AuthStore";

interface ProtectedRouteProps {
  allowedRoles: Array<"admin" | "company" | "user">;
}

export default function ProtectedRoute({ allowedRoles }: ProtectedRouteProps) {
  const { token, role } = useAuthStore();

  if (!token) {
    // Redirect to signin if not authenticated
    return <Navigate to="/signin" replace />;
  }

  if (role && !allowedRoles.includes(role)) {
    // Redirect to role-appropriate home dashboard if not permitted
    if (role === "admin") {
      return <Navigate to="/admin" replace />;
    } else if (role === "company") {
      return <Navigate to="/company/dashboard" replace />;
    } else {
      return <Navigate to="/dashboard" replace />;
    }
  }

  return <Outlet />;
}
