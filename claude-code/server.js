const express = require("express");
const { spawn } = require("child_process");
const path = require("path");

const app = express();
app.use(express.json());

const WEBHOOK_TOKEN = process.env.WEBHOOK_TOKEN || "change-me";
const PROJECTS_ROOT = process.env.PROJECTS_ROOT || "/projects";

// Auth middleware
app.use((req, res, next) => {
  const auth = req.headers["authorization"] || "";
  if (auth !== `Bearer ${WEBHOOK_TOKEN}`) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  next();
});

/**
 * POST /claude
 * Body: {
 *   prompt: string,          // The transcribed voice message
 *   session_id: string,      // Telegram chat_id — gives each chat its own memory
 * }
 */
app.post("/claude", async (req, res) => {
  const { prompt, session_id } = req.body;

  if (!prompt) {
    return res.status(400).json({ error: "prompt is required" });
  }

  console.log(`[claude] session=${session_id} cwd=${PROJECTS_ROOT} prompt="${prompt.slice(0, 80)}..."`);

  const runClaude = ({ withResume, withSkipPermissions }) =>
    new Promise((resolve) => {
      const args = ["--print"]; // Non-interactive / headless mode

      if (withSkipPermissions) {
        args.push("--dangerously-skip-permissions");
      }

      if (withResume && session_id) {
        args.push("--resume", String(session_id));
      }
      args.push(prompt);

      let stdout = "";
      let stderr = "";
      const proc = spawn("claude", args, {
        cwd: path.resolve(PROJECTS_ROOT),
        env: {
          ...process.env,
          HOME: "/home/node",
        },
        stdio: ["ignore", "pipe", "pipe"],
        timeout: 180_000,
      });

      proc.stdout.on("data", (d) => (stdout += d.toString()));
      proc.stderr.on("data", (d) => (stderr += d.toString()));

      proc.on("close", (code) => {
        resolve({
          code,
          stdout: stdout.trim(),
          stderr: stderr.trim(),
          used_resume: Boolean(withResume && session_id),
          used_skip_permissions: Boolean(withSkipPermissions),
        });
      });

      proc.on("error", (err) => {
        resolve({
          code: -1,
          stdout: "",
          stderr: err.message,
          used_resume: Boolean(withResume && session_id),
          used_skip_permissions: Boolean(withSkipPermissions),
        });
      });
    });

  const attempts = [];
  let attempt = await runClaude({ withResume: true, withSkipPermissions: true });
  attempts.push(attempt);

  // Common case in webhook usage: non-Claude session ids (e.g. "1") can yield empty output.
  if (attempt.code === 0 && !attempt.stdout && !attempt.stderr) {
    console.log("[claude] empty output with resume, retrying without resume");
    attempt = await runClaude({ withResume: false, withSkipPermissions: true });
    attempts.push(attempt);
  }

  // Fallback for environments where skip-permissions leads to empty completion.
  if (attempt.code === 0 && !attempt.stdout && !attempt.stderr) {
    console.log("[claude] still empty, retrying without skip-permissions");
    attempt = await runClaude({ withResume: false, withSkipPermissions: false });
    attempts.push(attempt);
  }

  if (attempt.code !== 0) {
    return res.status(500).json({
      ok: false,
      error: attempt.stderr || "Claude Code exited with error",
      exit_code: attempt.code,
      used_resume: attempt.used_resume,
      used_skip_permissions: attempt.used_skip_permissions,
      attempts: attempts.map((a, idx) => ({
        idx: idx + 1,
        code: a.code,
        used_resume: a.used_resume,
        used_skip_permissions: a.used_skip_permissions,
        stdout_len: a.stdout.length,
        stderr_len: a.stderr.length,
      })),
    });
  }

  const result = attempt.stdout || attempt.stderr;
  if (!result) {
    return res.status(502).json({
      ok: false,
      error: "Claude returned empty output",
      hint: "Try a new session_id or disable resume mapping from Telegram chat id",
      attempts: attempts.map((a, idx) => ({
        idx: idx + 1,
        code: a.code,
        used_resume: a.used_resume,
        used_skip_permissions: a.used_skip_permissions,
        stdout_len: a.stdout.length,
        stderr_len: a.stderr.length,
      })),
    });
  }

  return res.json({
    ok: true,
    result,
    session_id: session_id || null,
    cost: null,
    used_resume: attempt.used_resume,
  });
});

// Health check for Docker
app.get("/health", (_, res) => res.json({ status: "ok" }));

app.listen(3001, "0.0.0.0", () => {
  console.log("[claude-code webhook] listening on :3001");
});
