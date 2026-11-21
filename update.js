module.exports = {
  requires: { bundle: "dev" },
  run: [
    { method: "shell.run", params: { path: ".", message: "git pull --ff-only" } },
    { method: "shell.run", params: { path: "app", message: "node install.cjs" } }
  ]
};
