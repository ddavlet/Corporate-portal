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

  const args = [
    "--print", // Non-interactive / headless mode
    "--dangerously-skip-permissions", // Skip interactive permission prompts in Docker
    "--output-format",
    "json", // Structured output
  ];

  if (session_id) {
    args.push("--resume", String(session_id));
  }
  args.push(prompt);

  let stdout = "";
  let stderr = "";
  const proc = spawn("claude", args, {
    cwd: path.resolve(PROJECTS_ROOT),
    env: {
      ...process.env,
      HOME: "/root",
    },
    timeout: 180_000,
  });

  proc.stdout.on("data", (d) => (stdout += d.toString()));
  proc.stderr.on("data", (d) => (stderr += d.toString()));

  proc.on("close", (code) => {
    if (code !== 0) {
      return res.status(500).json({
        ok: false,
        error: stderr || "Claude Code exited with error",
        exit_code: code,
      });
    }
    try {
      const lines = stdout.trim().split("\n").filter(Boolean);
      const last = JSON.parse(lines[lines.length - 1]);
      return res.json({
        ok: true,
        result: last.result ?? last.content ?? stdout,
        session_id: last.session_id ?? session_id,
        cost: last.cost_usd ?? null,
      });
    } catch {
      return res.json({ ok: true, result: stdout, session_id: session_id || null });
    }
  });

  proc.on("error", (err) => {
    return res.status(500).json({
      ok: false,
      error: err.message,
    });
  });
});

// Health check for Docker
app.get("/health", (_, res) => res.json({ status: "ok" }));

app.listen(3001, "0.0.0.0", () => {
  console.log("[claude-code webhook] listening on :3001");
});
