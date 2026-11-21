const { spawn } = require("node:child_process");
const path = require("node:path");

const port = process.argv[2] || "50883";
const python = path.join(__dirname, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const child = spawn(python, ["-m", "kobi_music.cli", "serve", "--port", port], { cwd: __dirname, stdio: "inherit" });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
