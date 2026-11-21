module.exports = {
  version: "7.0",
  title: "Kobi Music Toolkit",
  description: "Local tools for recordings, score scans, MIDI, and playable audio",
  menu: async (_kernel, info) => {
    for (const script of ["install.js", "update.js"]) {
      if (info.running(script)) return [{ default: true, text: "Working", href: script }];
    }
    if (info.running("start.js")) {
      const terminal = { text: "Terminal", href: "start.js" };
      const local = info.local("start.js");
      if (!local?.url) return [{ ...terminal, default: true }];
      return [
        { default: true, text: "Open Toolkit", href: local.url },
        { text: "API Docs", href: `${local.url}/docs` },
        terminal
      ];
    }
    if (!info.exists("app/runtime/installed")) {
      return [{ default: true, text: "Install", href: "install.js" }];
    }
    return [
      { default: true, text: "Start", href: "start.js" },
      { text: "Update", href: "update.js" },
      { text: "Reinstall", href: "install.js" }
    ];
  }
};
