module.exports = {
  daemon: true,
  requires: { bundle: "dev" },
  run: [
    {
      method: "shell.run",
      params: {
        path: "app",
        message: "node launch.cjs {{port}}",
        on: [{ event: "/(http:\\/\\/[0-9.:]+)/", done: true }]
      }
    },
    { method: "local.set", params: { url: "{{input.event[1]}}" } }
  ]
};
