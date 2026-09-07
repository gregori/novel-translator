/* Minimal editorial behaviors: source/edit/preview tabs, debounced
   autosave with visible status, 409 conflict recovery without data
   loss, and localStorage backup for offline recovery. */
(function () {
  "use strict";

  var DEBOUNCE_MS = 1200;
  var REDUCED_MOTION = window.matchMedia(
    "(prefers-reduced-motion: reduce)"
  ).matches;

  function storageKey(context) {
    return "novel-translator:wc:" + context;
  }

  /* ---------- Tabs (source / edit / preview) ---------- */

  function wireTabs(scope) {
    var tabs = scope.querySelectorAll("[role=tab]");
    if (tabs.length === 0) return;
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (other) {
          var selected = other === tab;
          other.setAttribute("aria-selected", selected ? "true" : "false");
          var panel = document.getElementById(
            other.getAttribute("aria-controls")
          );
          if (panel) panel.hidden = !selected;
        });
        if (!REDUCED_MOTION) {
          var active = document.getElementById(tab.getAttribute("aria-controls"));
          if (active) active.scrollIntoView({ block: "nearest" });
        }
      });
    });
  }

  /* ---------- Autosave ---------- */

  function setStatus(el, state, text) {
    if (!el) return;
    el.dataset.state = state;
    el.textContent = text;
  }

  function wireAutosave(scope) {
    var form = scope.querySelector("form[data-autosave]");
    if (!form) return;
    var editor = form.querySelector("textarea[name=content]");
    var status = scope.querySelector("[data-save-status]");
    var versionInput = form.querySelector("input[name=version]");
    var conflictSlot = scope.querySelector("[data-conflict-slot]");
    var backupKey = storageKey(form.dataset.storageKey || "");

    var timer = null;
    var blockedMessage = null;
    var lastSaved = editor ? editor.value : null;

    function clearBackup() {
      try {
        localStorage.removeItem(backupKey);
      } catch (err) {
        /* storage unavailable */
      }
    }

    function backup() {
      try {
        localStorage.setItem(backupKey, JSON.stringify({ content: editor.value }));
      } catch (err) {
        /* storage full or unavailable — autosave still runs */
      }
    }

    function rejectSave(html, message) {
      if (conflictSlot) conflictSlot.innerHTML = html;
      blockedMessage = message;
      setStatus(status, "error", message);
      backup();
      return false;
    }

    function save() {
      if (!editor || !versionInput || blockedMessage) {
        return Promise.resolve(false);
      }
      if (editor.value === lastSaved) return Promise.resolve(true);
      setStatus(status, "saving", "Saving…");
      var data = new FormData(form);
      return fetch(form.action, {
        method: "POST",
        body: data,
        headers: { "X-Requested-With": "fetch" },
      })
        .then(function (response) {
          if (response.status === 409) {
            return response.text().then(function (html) {
              if (conflictSlot) conflictSlot.innerHTML = html;
              var isConflict =
                conflictSlot && conflictSlot.querySelector("[data-version]");
              var message = isConflict
                ? "Conflict — choose a version below"
                : "Not saved — reload this chapter";
              return rejectSave(html, message);
            });
          }
          if (!response.ok) {
            return response.text().then(function (html) {
              return rejectSave(html, "Not saved — reload this chapter");
            });
          }
          return response.text().then(function (html) {
            lastSaved = editor.value;
            var holder = document.createElement("div");
            holder.innerHTML = html;
            var updated = holder.querySelector("[data-version]");
            if (updated) versionInput.value = updated.dataset.version;
            var at = new Date().toLocaleTimeString();
            setStatus(status, "saved", "Saved " + at);
            if (conflictSlot) conflictSlot.innerHTML = "";
            clearBackup();
            return true;
          });
        })
        .catch(function () {
          setStatus(status, "error", "Offline — text kept locally");
          backup();
          return false;
        });
    }

    editor.addEventListener("input", function () {
      backup();
      clearTimeout(timer);
      if (blockedMessage) {
        setStatus(status, "error", blockedMessage);
        return;
      }
      setStatus(status, "idle", "Unsaved changes");
      timer = setTimeout(save, DEBOUNCE_MS);
    });

    form.addEventListener("submit", function (event) {
      clearTimeout(timer);
      save();
      event.preventDefault();
    });

    scope.addEventListener("submit", function (event) {
      var target = event.target;
      if (target.matches === undefined || !target.matches("[data-save-first]")) {
        return;
      }
      event.preventDefault();
      Promise.resolve(save()).then(function (saved) {
        if (saved) {
          clearBackup();
          target.submit();
        }
      });
    });

    scope.addEventListener("submit", function (event) {
      var target = event.target.closest("form[data-resolve-role]");
      if (!target) return;
      event.preventDefault();
      if (target.dataset.resolveRole === "mine") {
        var current = target.querySelector("input[name=version]");
        if (current) versionInput.value = current.value;
        blockedMessage = null;
        if (conflictSlot) conflictSlot.innerHTML = "";
        save();
        return;
      }
      if (target.dataset.resolveRole === "server") {
        var server = target
          .closest("[data-version]")
          .querySelector("input[data-server-content]");
        if (server) {
          editor.value = server.value;
          lastSaved = editor.value;
        }
        var serverVersion = target.closest("[data-version]");
        if (serverVersion) versionInput.value = serverVersion.dataset.version;
        blockedMessage = null;
        if (conflictSlot) conflictSlot.innerHTML = "";
        setStatus(status, "saved", "Using the saved server version");
        clearBackup();
      }
    });

    scope.addEventListener("submit", function (event) {
      var target = event.target.closest("form[data-clear-backup]");
      if (target && !event.defaultPrevented) clearBackup();
    });
  }

  /* ---------- Offline recovery ---------- */

  function wireRecovery(scope) {
    var form = scope.querySelector("form[data-autosave]");
    if (!form) return;
    var editor = form.querySelector("textarea[name=content]");
    var notice = scope.querySelector("[data-recovery]");
    if (!editor || !notice) return;
    var backupKey = storageKey(form.dataset.storageKey || "");
    var backup = null;
    try {
      backup = JSON.parse(localStorage.getItem(backupKey) || "null");
    } catch (err) {
      backup = null;
    }
    if (!backup || backup.content == null) return;
    if (backup.content === editor.value) return;
    var summary = notice.querySelector("[data-recovery-text]");
    if (summary) {
      summary.textContent =
        "Found " +
        backup.content.length.toLocaleString() +
        " characters of unsaved text saved locally on this device.";
    }
    notice.hidden = false;
    var restore = notice.querySelector("[data-recovery-restore]");
    if (restore) {
      restore.addEventListener("click", function () {
        editor.value = backup.content;
        editor.dispatchEvent(new Event("input", { bubbles: true }));
        notice.hidden = true;
        editor.focus();
      });
    }
    var dismiss = notice.querySelector("[data-recovery-dismiss]");
    if (dismiss) {
      dismiss.addEventListener("click", function () {
        notice.hidden = true;
        try {
          localStorage.removeItem(backupKey);
        } catch (err) {
          /* nothing to clean */
        }
      });
    }
  }

  /* ---------- Confirm discard ---------- */

  function wireConfirms(scope) {
    scope.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
      });
    });
  }

  function boot() {
    wireTabs(document);
    wireConfirms(document);
    document.querySelectorAll("[data-editor-root]").forEach(function (root) {
      wireRecovery(root);
      wireAutosave(root);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  /* Re-wire after HTMX swaps (search/filter partials). */
  document.body.addEventListener("htmx:afterSwap", function (event) {
    wireTabs(event.target);
    wireConfirms(event.target);
  });
})();
