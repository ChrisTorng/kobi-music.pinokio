const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = __dirname;
const data = path.join(root, "runtime");
const venv = path.join(root, ".venv");
const python = path.join(venv, process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const models = [
  { name: "dettato", sha: "9b724251794f2bbd5eaa43e54734e5a251829130" },
  { name: "copisteria", sha: "2be4a9d88c15fd6b36fe7c97e0fa816f08804570" }
];

function run(command, args) {
  console.log(">", command, ...args);
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", env: { ...process.env, UV_NO_PROGRESS: "1" } });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with code ${result.status}`);
}

function checkout({ name, sha }) {
  const dir = path.join(data, "source", name);
  fs.mkdirSync(dir, { recursive: true });
  if (!fs.existsSync(path.join(dir, ".git"))) run("git", ["-C", dir, "init"]);
  const head = spawnSync("git", ["-C", dir, "rev-parse", "HEAD"], { encoding: "utf8" });
  if (head.stdout.trim() !== sha) {
    run("git", ["-C", dir, "fetch", "--depth=1", `https://github.com/kobimusic/${name}.git`, sha]);
    run("git", ["-C", dir, "checkout", "--detach", "FETCH_HEAD"]);
  }
  return dir;
}

fs.mkdirSync(data, { recursive: true });
const marker = path.join(data, "installed");
fs.rmSync(marker, { force: true });
if (!fs.existsSync(python)) {
  run("uv", ["python", "install", "3.12"]);
  run("uv", ["venv", "--python", "3.12", venv]);
}
const sources = models.map(checkout);
const args = ["pip", "install", "--python", python, "-e", root];
for (const source of sources) args.push("-e", source);
if (["win32", "linux"].includes(process.platform)) args.push("--torch-backend", "auto");
run("uv", args);
run(python, ["-m", "kobi_music.setup_assets"]);
fs.writeFileSync(marker, new Date().toISOString());
