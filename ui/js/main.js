/* QuickPythonIDE 前端逻辑（阶段1）
 * 通过 window.pywebview.api 调用宿主的 RPC 接口：
 *   list_dir(path) / load_file(path) / save_file(path, content) / run_code(code, path)
 */
(function () {
  "use strict";

  let editor = null;
  let activePath = null;
  let lastParent = null;
  const openTabs = new Map(); // path -> { name, content, dirty }

  function api() {
    return window.pywebview.api;
  }

  // ---------------- 日志面板 ----------------
  function logLine(text, kind) {
    const log = document.getElementById("log");
    const span = document.createElement("span");
    span.className = "line " + (kind || "out");
    span.textContent = text + "\n";
    log.appendChild(span);
    log.scrollTop = log.scrollHeight;
  }
  function clearLog() {
    document.getElementById("log").innerHTML = "";
  }

  // ---------------- 工程树 ----------------
  async function renderTree(path) {
    const res = await api().list_dir(path);
    const tree = document.getElementById("file-tree");
    tree.innerHTML = "";
    if (!res.ok) {
      logLine("读取目录失败: " + res.error, "err");
      return;
    }
    lastParent = res.parent;
    res.items.forEach(function (item) {
      const li = document.createElement("li");
      li.className = "node " + (item.is_dir ? "dir" : "file");
      if (item.path === activePath) li.classList.add("active");
      li.textContent = (item.is_dir ? "📁 " : "📄 ") + item.name;
      li.onclick = function () {
        if (item.is_dir) {
          renderTree(item.path);
        } else {
          openFile(item.path);
        }
      };
      tree.appendChild(li);
    });
  }

  // ---------------- 标签管理 ----------------
  function renderTabs() {
    const tabs = document.getElementById("tabs");
    tabs.innerHTML = "";
    openTabs.forEach(function (tab, path) {
      const el = document.createElement("div");
      el.className = "tab" + (path === activePath ? " active" : "");
      el.textContent = (tab.dirty ? "• " : "") + tab.name;
      el.title = path;
      el.onclick = function () { activateTab(path); };
      tabs.appendChild(el);
    });
  }

  async function openFile(path) {
    let tab = openTabs.get(path);
    if (!tab) {
      const res = await api().load_file(path);
      if (!res.ok) {
        logLine("打开失败: " + res.error, "err");
        return;
      }
      const name = res.path.split(/[\\/]/).pop();
      tab = { name: name, content: res.content, dirty: false };
      openTabs.set(path, tab);
    }
    activePath = path;
    editor.setValue(tab.content);
    editor.clearHistory();
    renderTabs();
    renderTree(lastParent); // 高亮当前文件
    updateInspector(path, tab);
  }

  function activateTab(path) {
    const tab = openTabs.get(path);
    if (!tab) return;
    if (activePath && openTabs.has(activePath)) {
      openTabs.get(activePath).content = editor.getValue();
    }
    activePath = path;
    editor.setValue(tab.content);
    editor.clearHistory();
    renderTabs();
    updateInspector(path, tab);
  }

  function updateInspector(path, tab) {
    const body = document.getElementById("inspector-body");
    const lines = tab.content.split("\n").length;
    body.innerHTML =
      "<p><b>文件</b><br>" + esc(tab.name) + "</p>" +
      "<p><b>路径</b><br><span class='muted'>" + esc(path) + "</span></p>" +
      "<p><b>行数</b>: " + lines + "</p>";
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------------- 保存 / 运行 ----------------
  async function saveActive() {
    if (!activePath) { logLine("没有打开的文件", "err"); return; }
    const tab = openTabs.get(activePath);
    tab.content = editor.getValue();
    const res = await api().save_file(activePath, tab.content);
    if (res.ok) {
      tab.dirty = false;
      renderTabs();
      logLine("已保存: " + activePath, "ok");
    } else {
      logLine("保存失败: " + res.error, "err");
    }
  }

  async function runActive() {
    if (!activePath) { logLine("没有打开的文件，无法运行", "err"); return; }
    const tab = openTabs.get(activePath);
    tab.content = editor.getValue();
    clearLog();
    logLine("运行 " + activePath + " ...", "ok");
    const res = await api().run_code(tab.content, activePath);
    if (res.stdout) logLine(res.stdout, "out");
    if (res.stderr) logLine(res.stderr, "err");
    logLine(res.ok ? "--- 运行结束（正常） ---" : "--- 运行结束（异常） ---",
            res.ok ? "ok" : "err");
  }

  // ---------------- 初始化 ----------------
  function initEditor() {
    editor = CodeMirror.fromTextArea(document.getElementById("code"), {
      mode: { name: "python", version: 3, singleLineStringErrors: false },
      lineNumbers: true,
      indentUnit: 4,
      tabSize: 4,
      autofocus: true,
    });
    editor.on("change", function () {
      if (activePath && openTabs.has(activePath)) {
        const tab = openTabs.get(activePath);
        tab.content = editor.getValue();
        if (!tab.dirty) { tab.dirty = true; renderTabs(); }
      }
    });
  }

  function init() {
    initEditor();
    document.getElementById("btn-run").onclick = runActive;
    document.getElementById("btn-save").onclick = saveActive;
    document.getElementById("btn-new").onclick = function () {
      logLine("新建文件：在文件管理器建好空文件后，刷新树即可在此打开", "ok");
    };
    document.getElementById("btn-stop").onclick = function () {
      logLine("停止功能将在阶段3通过 subprocess 子进程实现", "err");
    };
    document.getElementById("btn-up").onclick = function () {
      if (lastParent) renderTree(lastParent);
    };
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveActive();
      }
    });
    // 从宿主根目录（main.py 所在目录）开始展示工程树
    renderTree(null);
  }

  if (window.pywebview) {
    init();
  } else {
    document.addEventListener("pywebviewready", init);
  }
})();
