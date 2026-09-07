import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { InterviewRoomPage } from "./pages/InterviewRoomPage";
import { InterviewsPage } from "./pages/InterviewsPage";
import { MemoriesPage } from "./pages/MemoriesPage";
import { PeoplePage } from "./pages/PeoplePage";
import { ScriptBookPage } from "./pages/ScriptBookPage";
import { ScriptLibraryPage } from "./pages/ScriptLibraryPage";
import { StudioPage } from "./pages/StudioPage";
import { LoginPage } from "./pages/LoginPage";
import { PublicReelPage } from "./pages/PublicReelPage";
import { api } from "./api/client";
import { isAuthenticationError } from "./api/errors";
import { QueryState } from "./components/QueryState";

function ProtectedApp() {
  const session = useQuery({ queryKey: ["auth-me"], queryFn: api.me, retry: false });
  if (session.isPending) return <div className="login-page"><p className="login-status">正在验证家庭空间……</p></div>;
  if (session.isError && isAuthenticationError(session.error)) return <Navigate to="/login" replace />;
  if (session.isError) return <div className="login-page"><div className="login-card"><QueryState queries={[session]} /></div></div>;
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/people" element={<PeoplePage />} />
        <Route path="/interviews" element={<InterviewsPage />} />
        <Route path="/interviews/:id" element={<InterviewRoomPage />} />
        <Route path="/evidence" element={<Navigate to="/memories" replace />} />
        <Route path="/memories" element={<MemoriesPage />} />
        <Route path="/scripts" element={<ScriptLibraryPage />} />
        <Route path="/scripts/:subjectId" element={<ScriptBookPage />} />
        <Route path="/studio" element={<StudioPage />} />
      </Routes>
    </AppShell>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/watch/:token" element={<PublicReelPage />} />
      <Route path="/*" element={<ProtectedApp />} />
    </Routes>
  );
}
