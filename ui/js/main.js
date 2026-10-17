/* QuickPythonIDE 前端逻辑（阶段3）
 * 通过 window.pywebview.api 调用宿主 RPC：
 *   list_dir(path) / load_file(path) / save_file(path, content) /
 *   delete_path(path) / backup_file(path) / python_versions() /
 *   run_code(code, path, python) / stop_code() / pip_install(packages, python)
 *
 * 阶段3 新增：run_code 改为异步子进程执行，输出经 window.appendOutput 实时推回，
 *           结束经 window.onRunFinished；新增停止、Python 版本切换、pip 安装、备份。
 */
(function () {
  "use strict";

  let editor = null;
  let activePath = null;
  let rootPath = null;
  const openTabs = new Map(); // path -> { name, content, dirty }

  // 窗体设计器状态
  const formControls = [];
  let ctrlId = 0;

  // 右键菜单上下文
  let ctxPath = null;
  let ctxIsDir = false;

  function api() {
    return window.pywebview.api;
  }

  // ---------------- 日志面板 ----------------
  function logLine(text, kind) {
    const log = document.getElementById("log");
    const span = document.createElement("span");
    span.className = "line " + (kind || "out");
    const ts = new Date().toLocaleTimeString();
    span.textContent = "[" + ts + "] " + text + "\n";
    log.appendChild(span);
    log.scrollTop = log.scrollHeight;
  }
  function clearLog() {
    document.getElementById("log").innerHTML = "";
  }

  // ---------------- 状态栏 ----------------
  function updateStatus() {
    const sel = document.getElementById("py-version");
    const interp = sel && sel.value ? sel.value : "默认 Python";
    const stI = document.getElementById("st-interp");
    const stF = document.getElementById("st-file");
    if (stI) stI.textContent = "解释器: " + interp;
    if (stF) stF.textContent = "文件: " + (activePath || "无");
  }

  // ---------------- 主题切换（深色/浅色，记忆到本地） ----------------
  function applyTheme(theme) {
    if (theme === "light") document.documentElement.setAttribute("data-theme", "light");
    else document.documentElement.removeAttribute("data-theme");
    const btn = document.getElementById("btn-theme");
    if (btn) btn.textContent = theme === "light" ? "☀️ 浅色" : "🌙 深色";
    try { localStorage.setItem("qpy-theme", theme); } catch (e) {}
    if (editor) editor.refresh();
  }
  function initTheme() {
    let theme = "dark";
    try { theme = localStorage.getItem("qpy-theme") || "dark"; } catch (e) {}
    applyTheme(theme);
    const btn = document.getElementById("btn-theme");
    if (btn) btn.onclick = function () {
      const cur = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
      applyTheme(cur === "light" ? "dark" : "light");
    };
  }

  // ---------------- 日志导出 ----------------
  function exportLog() {
    const text = document.getElementById("log").textContent;
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    a.href = url;
    a.download = "quickpythonide-log-" + ts + ".txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    logLine("已导出日志", "ok");
  }

  // ---------------- 工程树（递归展开/折叠） ----------------
  function makeNode(item) {
    const li = document.createElement("li");
    li.className = "node " + (item.is_dir ? "dir" : "file");
    li.dataset.path = item.path;

    const twisty = document.createElement("span");
    twisty.className = "twisty";
    twisty.textContent = item.is_dir ? "▸" : "";
    li.appendChild(twisty);
    li.appendChild(document.createTextNode((item.is_dir ? "📁 " : "📄 ") + item.name));

    if (item.is_dir) {
      li.onclick = function (e) {
        e.stopPropagation();
        expandDir(li);
      };
    } else {
      li.onclick = function (e) {
        e.stopPropagation();
        openFile(item.path);
      };
    }
    li.oncontextmenu = function (e) {
      e.preventDefault();
      e.stopPropagation();
      openCtxForNode(e, item);
    };
    return li;
  }

  async function expandDir(li) {
    const path = li.dataset.path;
    const twisty = li.querySelector(":scope > .twisty");
    let childUl = li.querySelector(":scope > .children");
    if (!childUl) {
      childUl = document.createElement("ul");
      childUl.className = "children";
      li.appendChild(childUl);
    }
    if (li.dataset.loaded === "1") {
      childUl.classList.toggle("collapsed");
      if (twisty) twisty.textContent = childUl.classList.contains("collapsed") ? "▸" : "▾";
      return;
    }
    const res = await api().list_dir(path);
    if (!res.ok) {
      logLine("读取目录失败: " + res.error, "err");
      return;
    }
    li.dataset.loaded = "1";
    res.items.forEach(function (it) {
      childUl.appendChild(makeNode(it));
    });
    if (twisty) twisty.textContent = "▾";
  }

  async function renderRoot() {
    const res = await api().list_dir(null);
    const tree = document.getElementById("file-tree");
    tree.innerHTML = "";
    if (!res.ok) {
      logLine("读取工程根目录失败: " + res.error, "err");
      return;
    }
    rootPath = res.path;
    res.items.forEach(function (it) {
      tree.appendChild(makeNode(it));
    });
  }

  // ---------------- 右键菜单 ----------------
  function showCtx(x, y, items) {
    const menu = document.getElementById("ctx-menu");
    menu.innerHTML = "";
    items.forEach(function (it) {
      if (it.sep) {
        const s = document.createElement("div");
        s.className = "sep";
        menu.appendChild(s);
        return;
      }
      const el = document.createElement("div");
      el.className = "item";
      el.textContent = it.label;
      el.onclick = function (e) {
        e.stopPropagation();
        hideCtx();
        it.action();
      };
      menu.appendChild(el);
    });
    menu.style.left = x + "px";
    menu.style.top = y + "px";
    menu.classList.remove("hidden");
  }
  function hideCtx() {
    document.getElementById("ctx-menu").classList.add("hidden");
  }

  function openCtxForNode(e, item) {
    ctxPath = item.path;
    ctxIsDir = item.is_dir;
    if (item.is_dir) {
      showCtx(e.clientX, e.clientY, [
        { label: "新建 .py", action: function () { newFile(".py"); } },
        { label: "新建 .json", action: function () { newFile(".json"); } },
        { label: "刷新", action: renderRoot },
        { sep: true },
        { label: "删除", action: function () { deleteItem(ctxPath); } },
      ]);
    } else {
      showCtx(e.clientX, e.clientY, [
        { label: "删除", action: function () { deleteItem(ctxPath); } },
      ]);
    }
  }

  async function newFile(ext) {
    const name = window.prompt("新建文件名（例如 main" + ext + "）");
    if (!name) return;
    const base = ctxIsDir ? ctxPath : rootPath;
    const full = base.replace(/[\\/]$/, "") + "/" + name;
    const content = ext === ".py" ? "# " + name + "\n" : "{}\n";
    const res = await api().save_file(full, content);
    if (res.ok) {
      logLine("已新建: " + full, "ok");
      renderRoot();
    } else {
      logLine("新建失败: " + res.error, "err");
    }
  }

  async function deleteItem(path) {
    const label = path.split(/[\\/]/).pop();
    if (!window.confirm("确认删除 " + label + " ？")) return;
    const res = await api().delete_path(path);
    if (res.ok) {
      logLine("已删除: " + label, "ok");
      renderRoot();
    } else {
      logLine("删除失败: " + res.error, "err");
    }
  }

  // ---------------- 标签管理 ----------------
  function renderTabs() {
    const tabs = document.getElementById("tabs");
    tabs.innerHTML = "";
    openTabs.forEach(function (tab, path) {
      const el = document.createElement("div");
      el.className = "tab" + (path === activePath ? " active" : "");
      const label = document.createElement("span");
      label.textContent = (tab.dirty ? "• " : "") + tab.name;
      label.title = path;
      label.onclick = function () { activateTab(path); };
      const close = document.createElement("span");
      close.className = "close";
      close.textContent = "×";
      close.onclick = function (e) {
        e.stopPropagation();
        closeTab(path);
      };
      el.appendChild(label);
      el.appendChild(close);
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
    updateInspector(path, tab);
    updateStatus();
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
    updateStatus();
  }

  function closeTab(path) {
    const tab = openTabs.get(path);
    if (tab && tab.dirty) {
      if (!window.confirm("文件 " + tab.name + " 未保存，确定关闭？")) return;
    }
    openTabs.delete(path);
    if (activePath === path) {
      const next = openTabs.keys().next();
      if (!next.done) {
        activateTab(next.value);
      } else {
        activePath = null;
        editor.setValue("");
        document.getElementById("inspector-body").innerHTML = '<p class="muted">未打开文件</p>';
      }
    }
    renderTabs();
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
    const py = document.getElementById("py-version").value || "";
    clearLog();
    logLine("运行 " + activePath + (py ? "  [使用 " + py + "]" : "") + " ...", "ok");
    const res = await api().run_code(tab.content, activePath, py);
    if (!res.ok) {
      logLine(res.error || "运行启动失败", "err");
      return;
    }
    // 异步模式：输出经 window.appendOutput 实时推回，结束经 window.onRunFinished
    document.getElementById("btn-run").disabled = true;
    document.getElementById("btn-stop").disabled = false;
  }

  async function stopActive() {
    const res = await api().stop_code();
    if (res.ok) logLine("已发送停止信号，等待进程退出…", "warn");
    else logLine(res.error || "停止失败", "err");
  }

  // 运行「窗体设计」里的控件 + 编辑器里的控制器代码，弹出 tkinter 真实窗口。
  // 控件 id 在日志中打印，控制器用 ui.on("id", fn) 绑定按钮，ui.get/ui.set 读写控件。
  // 运行前先检测当前解释器是否有 tkinter（标准库，但需 Tcl/Tk 运行文件）；缺失则尝试自动修复。
  async function runForm() {
    if (!formControls.length) {
      logLine("请先在「窗体设计」里添加控件（按钮/标签/文本框/多行文本）", "err");
      return;
    }
    const code = editor.getValue();
    const py = document.getElementById("py-version").value || "";
    clearLog();
    const ids = formControls.map(function (c) {
      const t = c.type === "Button" ? "按钮" : c.type === "Label" ? "标签"
        : c.type === "TextBox" ? "文本框" : c.type === "TextArea" ? "多行文本" : c.type;
      return c.id + "(" + t + ")";
    }).join(", ");
    logLine("启动 tkinter 窗体，运行在 " + (py || "默认解释器") + " ...", "ok");
    logLine("控件ID: " + ids, "warn");
    logLine("tkinter 是标准库但需 Tcl/Tk 运行文件；若解释器缺失会自动尝试修复。", "out");

    // 1) 检测 tkinter 是否可用
    let chk = await api().check_tkinter(py);
    if (!chk.ok) {
      logLine("未检测到 tkinter（" + (chk.error || "未知原因") + "），尝试自动修复…", "warn");
      const fix = await api().ensure_tkinter(py);
      if (!fix.ok) {
        logLine("⚠️ 无法自动修复 tkinter。", "err");
        if (fix.target) logLine("需要为 Python " + fix.target + " 补齐 Tcl/Tk 文件。", "err");
        if (fix.dest) logLine("目标目录: " + fix.dest, "err");
        logLine("补齐方法：下载同版本完整 Python 安装包，把其中的 tcl/ 目录、_tkinter.pyd、tcl*.dll、tk*.dll 拷到上面的目标目录；或用「修复 Tk」按钮再试。", "err");
        return;
      }
      logLine("已修复：" + (fix.action || ""), "ok");
    }

    // 2) 真正运行窗体
    const res = await api().run_form(JSON.stringify(formControls), code, py);
    if (!res.ok) {
      logLine(res.error || "窗体启动失败", "err");
      return;
    }
    // 异步模式：输出经 window.appendOutput 推回；结束经 window.onRunFinished 复位按钮
    document.getElementById("btn-run").disabled = true;
    document.getElementById("btn-stop").disabled = false;
  }

  // 单独检测当前解释器的 tkinter 可用性（不运行窗体）
  async function checkTk() {
    const py = document.getElementById("py-version").value || "";
    const res = await api().check_tkinter(py);
    if (res.ok) {
      logLine("✅ 当前解释器可用 tkinter：" + res.python, "ok");
    } else {
      logLine("❌ 当前解释器缺少 tkinter：" + (res.error || ""), "err");
      logLine("提示：tkinter 无法通过 pip 安装，缺的是 Tcl/Tk 运行文件。点「修复 Tk」自动尝试补齐。", "out");
    }
  }

  // 自动尝试补齐 Tcl/Tk 运行文件（从同版本完整 Python 复制）
  async function fixTk() {
    const py = document.getElementById("py-version").value || "";
    logLine("尝试修复 tkinter（自动从同版本完整 Python 复制 Tcl/Tk 文件）…", "warn");
    const res = await api().ensure_tkinter(py);
    if (res.ok) {
      logLine("✅ " + (res.action || "tkinter 已可用"), "ok");
    } else {
      logLine("⚠️ " + (res.action || "修复失败"), "err");
      if (res.target) logLine("需要为 Python " + res.target + " 补齐 Tcl/Tk 文件到 " + (res.dest || ""), "err");
    }
  }

  // 宿主推流回调：实时把子进程输出写入日志面板
  window.appendOutput = function (text, kind) {
    logLine(text, kind);
  };
  // 宿主通知运行结束：恢复按钮状态
  window.onRunFinished = function (ok, rc) {
    document.getElementById("btn-run").disabled = false;
    document.getElementById("btn-stop").disabled = true;
  };

  async function loadPythonVersions() {
    const sel = document.getElementById("py-version");
    if (!sel) return;
    const res = await api().python_versions();
    let embeddedPath = null;
    if (res.ok && res.versions.length) {
      res.versions.forEach(function (v) {
        const o = document.createElement("option");
        o.value = v.path;
        o.textContent = v.label || v.path;
        sel.appendChild(o);
        if (v.embedded && !embeddedPath) embeddedPath = v.path;
      });
    } else {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "默认 Python";
      sel.appendChild(o);
    }
    // 默认用 root/ 里的嵌入式解释器（免安装、不依赖系统 Python）
    if (embeddedPath) sel.value = embeddedPath;
    updateStatus();
  }

  async function installPip() {
    const inp = document.getElementById("pip-pkg");
    const pkg = inp.value.trim();
    if (!pkg) { logLine("请输入要安装的包名", "err"); return; }
    const py = document.getElementById("py-version").value || "";
    logLine("pip install " + pkg + (py ? "  [" + py + "]" : "") + " ...", "warn");
    const res = await api().pip_install(pkg, py);
    if (res.output) logLine(res.output, "out");
    logLine(res.ok ? "--- 安装完成 ---" : "--- 安装失败 ---", res.ok ? "ok" : "err");
  }

  async function backupActive() {
    if (!activePath) { logLine("没有打开的文件", "err"); return; }
    const res = await api().backup_file(activePath);
    if (res.ok) logLine("已备份: " + res.path, "ok");
    else logLine(res.error || "备份失败", "err");
  }

  // ---------------- 窗体设计器 ----------------
  function addControl(type) {
    const canvas = document.getElementById("form-canvas");
    const ctrl = document.createElement("div");
    ctrl.className = "fb-control";
    const x = 20 + (formControls.length % 6) * 90;
    const y = 20 + Math.floor(formControls.length / 6) * 50;
    ctrl.style.left = x + "px";
    ctrl.style.top = y + "px";
    const text = type === "Button" ? "按钮" : type === "Label" ? "标签"
      : type === "TextBox" ? "文本框" : type === "TextArea" ? "多行文本" : type;
    ctrl.textContent = text;
    const id = "c" + ++ctrlId;
    ctrl.dataset.id = id;
    ctrl.title = id; // 便于在控制器里用 ui.on("c1", fn) 绑定
    canvas.appendChild(ctrl);
    formControls.push({ id: id, type: type, x: x, y: y, text: text });
    bindControlDrag(ctrl);
    selectControl(ctrl);
  }

  function selectControl(ctrl) {
    document.querySelectorAll(".fb-control").forEach(function (c) {
      c.classList.remove("selected");
    });
    ctrl.classList.add("selected");
  }

  function bindControlDrag(ctrl) {
    ctrl.addEventListener("mousedown", function (e) {
      e.preventDefault();
      selectControl(ctrl);
      const id = ctrl.dataset.id;
      const startX = e.clientX, startY = e.clientY;
      const ox = parseInt(ctrl.style.left, 10), oy = parseInt(ctrl.style.top, 10);
      function move(ev) {
        const nx = ox + (ev.clientX - startX);
        const ny = oy + (ev.clientY - startY);
        ctrl.style.left = nx + "px";
        ctrl.style.top = ny + "px";
        const rec = formControls.find(function (c) { return c.id === id; });
        if (rec) { rec.x = nx; rec.y = ny; }
      }
      function up() {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
      }
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
  }

  async function exportForm() {
    if (!rootPath) { logLine("工程根目录未知", "err"); return; }
    const data = { version: 1, controls: formControls };
    const path = rootPath.replace(/[\\/]$/, "") + "/form.ui.json";
    const res = await api().save_file(path, JSON.stringify(data, null, 2));
    if (res.ok) {
      logLine("已导出窗体布局: " + path + "（" + formControls.length + " 个控件）", "ok");
    } else {
      logLine("导出失败: " + res.error, "err");
    }
  }

  // ---------------- 视图切换 ----------------
  function switchView(view) {
    const wrap = editor.getWrapperElement();
    const designer = document.getElementById("designer");
    if (view === "design") {
      wrap.classList.add("hidden");
      designer.classList.remove("hidden");
    } else {
      designer.classList.add("hidden");
      wrap.classList.remove("hidden");
      editor.refresh();
    }
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
    initTheme();
    initEditor();

    document.getElementById("btn-run").onclick = runActive;
    document.getElementById("btn-save").onclick = saveActive;
    document.getElementById("btn-stop").onclick = stopActive;
    document.getElementById("btn-run-form").onclick = runForm;
    document.getElementById("btn-pip").onclick = installPip;
    document.getElementById("btn-backup").onclick = backupActive;
    document.getElementById("btn-clear-log").onclick = clearLog;
    document.getElementById("btn-export-log").onclick = exportLog;
    const pySel = document.getElementById("py-version");
    if (pySel) pySel.addEventListener("change", updateStatus);
    document.getElementById("btn-new").onclick = function () {
      ctxPath = rootPath; ctxIsDir = true; newFile(".py");
    };
    document.getElementById("btn-up").onclick = function () {
      // 用展开/折叠代替导航，这里刷新根目录
      renderRoot();
    };

    // 工程树空白区域右键
    const tree = document.getElementById("file-tree");
    tree.oncontextmenu = function (e) {
      e.preventDefault();
      ctxPath = rootPath; ctxIsDir = true;
      showCtx(e.clientX, e.clientY, [
        { label: "新建 .py", action: function () { newFile(".py"); } },
        { label: "新建 .json", action: function () { newFile(".json"); } },
        { label: "刷新", action: renderRoot },
      ]);
    };

    // 视图切换
    document.querySelectorAll(".view-btn").forEach(function (b) {
      b.onclick = function () {
        document.querySelectorAll(".view-btn").forEach(function (x) {
          x.classList.remove("active");
        });
        b.classList.add("active");
        switchView(b.dataset.view);
      };
    });

    // 窗体设计器面板
    document.querySelectorAll(".palette button[data-type]").forEach(function (b) {
      b.onclick = function () { addControl(b.dataset.type); };
    });
    document.getElementById("btn-export-form").onclick = exportForm;
    document.getElementById("btn-check-tk").onclick = checkTk;
    document.getElementById("btn-fix-tk").onclick = fixTk;

    // 全局：点击/滚动关闭右键菜单
    document.addEventListener("click", hideCtx);
    document.addEventListener("contextmenu", function (e) {
      if (e.target.id !== "file-tree" && !e.target.closest(".node")) hideCtx();
    });

    // 快捷键
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault(); saveActive();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "r") {
        e.preventDefault(); runActive();
      }
    });

    renderRoot();
    loadPythonVersions();
    updateStatus();
  }

  if (window.pywebview) {
    init();
  } else {
    document.addEventListener("pywebviewready", init);
  }
})();
