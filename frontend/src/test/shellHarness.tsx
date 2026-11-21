import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";

export default function AppShellHarness() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="*" element={<p>content</p>} />
      </Route>
    </Routes>
  );
}
