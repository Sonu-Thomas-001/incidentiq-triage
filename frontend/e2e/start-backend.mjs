// Starts an isolated backend for E2E: fresh SQLite file, synthetic seed, no external integrations.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import path from "node:path";

const backend = path.resolve(import.meta.dirname, "..", "..", "backend");
const venvPy = process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python";
const py = existsSync(path.join(backend, venvPy)) ? path.join(backend, venvPy) : "python";
const db = path.join(backend, "e2e.db");
if (existsSync(db)) rmSync(db);

const env = {
  ...process.env,
  DATABASE_URL: "sqlite:///./e2e.db",
  DEMO_PASSWORD: process.env.E2E_PASSWORD ?? "E2e-Pass-123!",
  CORS_ORIGINS: '["http://localhost:5174"]',
  SERVICENOW_ENABLED: "false",
  GEMINI_ENABLED: "false",
};
for (const args of [["-m", "alembic", "upgrade", "head"], ["-m", "app.db.seed"]]) {
  const r = spawnSync(py, args, { cwd: backend, env, stdio: "inherit" });
  if (r.status !== 0) process.exit(r.status ?? 1);
}
const srv = spawn(py, ["-m", "uvicorn", "app.main:app", "--port", "8100"], { cwd: backend, env, stdio: "inherit" });
const stop = () => srv.kill();
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
srv.on("exit", (c) => process.exit(c ?? 0));
