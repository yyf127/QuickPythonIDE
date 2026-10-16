/* QuickPythonIDE 前端逻辑（阶段2）
 * 通过 window.pywebview.api 调用宿主 RPC：
 *   list_dir(path) / load_file(path) / save_file(path, content) /
 *   run_code(code, path) / delete_path(path)
 *
 * 阶段2 新增：工程树展开/折叠 + 右键菜单、多标签关闭、代码/窗体设计视图切换。
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
    clearLog();
    logLine("运行 " + activePath + " ...", "ok");
    const res = await api().run_code(tab.content, activePath);
    if (res.stdout) logLine(res.stdout, "out");
    if (res.stderr) logLine(res.stderr, "err");
    logLine(res.ok ? "--- 运行结束（正常） ---" : "--- 运行结束（异常） ---",
            res.ok ? "ok" : "err");
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
    const text = type === "Button" ? "按钮" : type === "Label" ? "标签" : "文本框";
    ctrl.textContent = text;
    const id = "c" + ++ctrlId;
    ctrl.dataset.id = id;
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
    initEditor();

    document.getElementById("btn-run").onclick = runActive;
    document.getElementById("btn-save").onclick = saveActive;
    document.getElementById("btn-new").onclick = function () {
      ctxPath = rootPath; ctxIsDir = true; newFile(".py");
    };
    document.getElementById("btn-stop").onclick = function () {
      logLine("停止功能将在阶段3通过 subprocess 子进程实现", "err");
    };
    document.getElementById("btn-up").onclick = function () {
      // 阶段2 用展开/折叠代替导航，这里刷新根目录
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
  }

  if (window.pywebview) {
    init();
  } else {
    document.addEventListener("pywebviewready", init);
  }
})();
