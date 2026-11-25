(() => {
  function initializeNavigation() {
    const sidebar = document.getElementById("app-sidebar");
    const toggle = document.getElementById("menu-toggle");
    const overlay = document.getElementById("sidebar-overlay");

    if (!sidebar || !toggle || !overlay) return;

    const closeSidebar = () => {
      sidebar.classList.remove("is-open");
      sidebar.inert = true;
      overlay.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Open navigation");
      document.body.classList.remove("menu-open");
    };

    const synchronizeSidebar = (event) => {
      if (event.matches) {
        sidebar.classList.remove("is-open");
        sidebar.inert = false;
        overlay.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
        toggle.setAttribute("aria-label", "Open navigation");
        document.body.classList.remove("menu-open");
      } else if (toggle.getAttribute("aria-expanded") !== "true") {
        closeSidebar();
      }
    };

    const openSidebar = () => {
      sidebar.classList.add("is-open");
      sidebar.inert = false;
      overlay.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      toggle.setAttribute("aria-label", "Close navigation");
      document.body.classList.add("menu-open");
    };

    toggle.addEventListener("click", () => {
      if (toggle.getAttribute("aria-expanded") === "true") {
        closeSidebar();
      } else {
        openSidebar();
      }
    });

    overlay.addEventListener("click", closeSidebar);
    sidebar.querySelectorAll("a").forEach((link) => {
      if (link.pathname === window.location.pathname) {
        sidebar.querySelectorAll("a[aria-current='page']").forEach((activeLink) => {
          activeLink.removeAttribute("aria-current");
        });
        link.setAttribute("aria-current", "page");
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        closeSidebar();
        toggle.focus();
      }
    });

    const desktopViewport = window.matchMedia("(min-width: 1024px)");
    synchronizeSidebar(desktopViewport);
    desktopViewport.addEventListener("change", synchronizeSidebar);
  }

  function initializeMissionBoard() {
    const board = document.getElementById("mission-board");
    const configElement = document.getElementById("mission-config");
    if (!board || !configElement) return;

    const config = JSON.parse(configElement.textContent);
    const grid = document.getElementById("mission-grid");
    const dateInput = document.getElementById("mission-date");
    const dateReadable = document.getElementById("mission-date-readable");
    const resultDate = document.getElementById("mission-result-date");
    const searchInput = document.getElementById("mission-search");
    const statusFilter = document.getElementById("mission-status-filter");
    const categoryFilter = document.getElementById("mission-category-filter");
    const difficultyFilter = document.getElementById("mission-difficulty-filter");
    const loadingMessage = document.getElementById("mission-loading");
    const errorPanel = document.getElementById("mission-error");
    const errorMessage = document.getElementById("mission-error-message");
    const emptyPanel = document.getElementById("mission-empty");
    const clearBanner = document.getElementById("mission-clear-banner");
    const dialog = document.getElementById("mission-dialog");
    const missionForm = document.getElementById("mission-form");
    const recurrenceSelect = missionForm.elements.namedItem("recurrence_type");
    const weekdaysField = missionForm.querySelector('[data-field="recurrence_days"]');
    const formErrors = document.getElementById("mission-form-errors");
    const submitButton = document.getElementById("mission-submit");
    const submitLabel = submitButton.querySelector(".mission-submit-label");
    const submitSpinner = submitButton.querySelector(".mission-submit-spinner");
    const toast = document.getElementById("mission-toast");
    const pendingActions = new Set();
    let missionTasks = [];
    let activeController = null;
    let requestSequence = 0;
    let searchTimer = null;
    let toastTimer = null;
    let editingTaskId = null;
    const creationKeyStorage = "lifegame-task-create-key";
    const createIdempotencyKey = () => window.crypto && window.crypto.randomUUID
      ? window.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const keyField = missionForm.elements.namedItem("idempotency_key");
    let creationRequestKey = keyField?.value || createIdempotencyKey();
    try {
      creationRequestKey = sessionStorage.getItem(creationKeyStorage) || creationRequestKey;
      sessionStorage.setItem(creationKeyStorage, creationRequestKey);
    } catch (_error) {
      // The hidden form key still protects ordinary duplicate submissions.
    }

    function formatDate(dateString, options) {
      const [year, month, day] = dateString.split("-").map(Number);
      return new Intl.DateTimeFormat("en", options).format(
        new Date(year, month - 1, day)
      );
    }

    function setSelectedDate(dateString) {
      dateInput.value = dateString;
      dateReadable.textContent = formatDate(dateString, {
        weekday: "long",
        month: "long",
        day: "numeric",
        year: "numeric",
      });
      resultDate.textContent = formatDate(dateString, {
        month: "short",
        day: "numeric",
      });
    }

    function dateByOffset(dateString, offset) {
      const [year, month, day] = dateString.split("-").map(Number);
      const next = new Date(Date.UTC(year, month - 1, day + offset));
      return next.toISOString().slice(0, 10);
    }

    function currentFilters() {
      return {
        status: statusFilter.value,
        category: categoryFilter.value,
        difficulty: difficultyFilter.value,
        search: searchInput.value.trim(),
      };
    }

    function requestUrl() {
      const params = new URLSearchParams({ date: dateInput.value });
      Object.entries(currentFilters()).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      return `${config.dailyUrl}?${params.toString()}`;
    }

    function syncAddressBar() {
      const params = new URLSearchParams({ date: dateInput.value });
      Object.entries(currentFilters()).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      window.history.replaceState({}, "", `${window.location.pathname}?${params}`);
    }

    function showToast(message, kind = "success") {
      toast.textContent = message;
      toast.dataset.kind = kind;
      toast.hidden = false;
      window.clearTimeout(toastTimer);
      toastTimer = window.setTimeout(() => {
        toast.hidden = true;
      }, 3600);
    }

    function setSummary(summary) {
      const completed = document.getElementById("mission-completed-count");
      const total = document.getElementById("mission-total-count");
      const percent = Math.round(summary.completion_percentage || 0);
      completed.textContent = summary.completed;
      total.textContent = summary.total_scheduled;
      document.getElementById("mission-progress-percent").firstChild.textContent =
        String(percent);
      document.getElementById("mission-stat-completed").textContent =
        summary.completed;
      document.getElementById("mission-stat-pending").textContent =
        summary.pending;
      document.getElementById("mission-stat-skipped").textContent =
        summary.skipped;
      document.getElementById("mission-stat-total").textContent =
        summary.total_scheduled;
      document.getElementById("mission-progress-fill").style.width =
        `${percent}%`;
      document
        .querySelector(".mission-progress-track")
        .setAttribute("aria-valuenow", String(percent));
    }

    function makeElement(tag, className, text) {
      const element = document.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined) element.textContent = text;
      return element;
    }

    function makeAction(label, action, className, occurrence) {
      const button = makeElement("button", className, label);
      button.type = "button";
      button.dataset.action = action;
      button.dataset.occurrenceId = occurrence.id;
      return button;
    }

    function taskActionUrl(template, taskId) {
      return template.replace("/0/", `/${taskId}/`);
    }

    function occurrenceActionUrl(template, occurrenceId) {
      return template.replace("/0/", `/${occurrenceId}/`);
    }

    function buildMissionCard(occurrence) {
      const card = makeElement(
        "article",
        `mission-card difficulty-${occurrence.difficulty.toLowerCase()} status-${occurrence.status.toLowerCase()}`
      );
      card.dataset.occurrenceId = occurrence.id;
      card.dataset.taskId = occurrence.task_id;

      const heading = makeElement("header", "mission-card-heading");
      const categoryMark = makeElement("span", "mission-category-mark", "✦");
      categoryMark.style.setProperty("--category-color", occurrence.category_color);
      categoryMark.setAttribute("aria-hidden", "true");
      const tags = makeElement("div", "mission-card-tags");
      tags.append(
        makeElement("span", "mission-category-name", occurrence.category),
        makeElement("span", "mission-difficulty-badge", occurrence.difficulty_label)
      );

      const menu = makeElement("details", "mission-menu");
      const summary = makeElement("summary", "", "•••");
      summary.setAttribute("aria-label", "Mission actions");
      const menuItems = makeElement("div", "mission-menu-items");
      const edit = makeElement("a", "", "Edit mission");
      edit.href = taskActionUrl(config.editPageUrlTemplate, occurrence.task_id);
      edit.dataset.action = "edit";
      edit.dataset.taskId = occurrence.task_id;
      menuItems.append(edit);
      const archive = makeElement("button", "", "Archive mission");
      archive.type = "button";
      archive.dataset.action = "archive";
      archive.dataset.taskId = occurrence.task_id;
      menuItems.append(archive);
      menu.append(summary, menuItems);
      heading.append(categoryMark, tags, menu);

      const title = makeElement("h3", "mission-title", occurrence.title);
      const description = makeElement(
        "p",
        "mission-description",
        occurrence.description || "No mission briefing provided."
      );
      const meta = makeElement("div", "mission-card-meta");
      meta.append(
        makeElement("span", "", `${occurrence.xp_reward} XP reward`),
        makeElement(
          "span",
          "",
          occurrence.estimated_minutes
            ? `${occurrence.estimated_minutes} min`
            : "Flexible time"
        ),
        makeElement("span", "", formatDate(occurrence.scheduled_date, {
          month: "short",
          day: "numeric",
          year: "numeric",
        }))
      );

      const state = makeElement("div", "mission-card-state");
      const status = makeElement("span", "mission-status-label");
      status.append(makeElement("i"), document.createTextNode(occurrence.status_label));
      state.append(status);
      if (occurrence.completed_at) {
        const time = makeElement(
          "time",
          "",
          new Intl.DateTimeFormat("en", {
            month: "short",
            day: "numeric",
            year: "numeric",
            hour: "numeric",
            minute: "2-digit",
          }).format(new Date(occurrence.completed_at))
        );
        time.dateTime = occurrence.completed_at;
        state.append(time);
      }

      const actions = makeElement("footer", "mission-card-actions");
      if (occurrence.status === "PENDING") {
        actions.append(
          makeAction("COMPLETE MISSION", "complete", "mission-complete-button", occurrence),
          makeAction("SKIP", "skip", "mission-skip-button", occurrence)
        );
      } else if (occurrence.status === "COMPLETED") {
        actions.append(
          makeElement("span", "mission-completed-caption", "MISSION COMPLETE"),
          makeAction("UNDO", "undo", "mission-undo-button", occurrence)
        );
      } else {
        actions.append(makeElement("span", "mission-skipped-caption", "MISSION SKIPPED"));
      }

      card.append(heading, title, description, meta, state, actions);
      return card;
    }

    function hasActiveFilters() {
      return Object.values(currentFilters()).some(Boolean);
    }

    function renderEmptyState(tasks, summary, hasActiveTasks) {
      const hasTasks = tasks.length > 0;
      emptyPanel.hidden = hasTasks;
      if (hasTasks) return;

      const title = document.getElementById("mission-empty-title");
      const copy = document.getElementById("mission-empty-copy");
      const kicker = document.getElementById("mission-empty-kicker");
      const createButton = document.getElementById("empty-create-mission");
      createButton.hidden = hasActiveFilters();
      createButton.textContent = hasActiveTasks
        ? "CREATE MISSION"
        : "CREATE YOUR FIRST MISSION";

      if (hasActiveFilters()) {
        kicker.textContent = "NO MATCHING MISSIONS";
        title.textContent = "No missions match your search.";
        copy.textContent = "Try another search or clear one of the filters.";
      } else if (
        summary.total_scheduled > 0 &&
        summary.pending === 0 &&
        summary.skipped === 0
      ) {
        kicker.textContent = "DAILY QUESTS CLEARED";
        title.textContent = "All daily missions completed. Excellent work, Player!";
        copy.textContent = "Your progress is recorded. You can undo a completion from its mission card.";
      } else if (!hasActiveTasks) {
        kicker.textContent = "NO MISSIONS DETECTED";
        title.textContent = "Your journey begins with your first mission.";
        copy.textContent = "Your next adventure starts here. Create a mission and begin your journey.";
      } else {
        kicker.textContent = "NO MISSIONS SCHEDULED";
        title.textContent = "No missions detected for this date.";
        copy.textContent = "Choose another day or create a mission that matches this schedule.";
      }
    }

    function renderMissions(tasks, summary, hasActiveTasks) {
      missionTasks = tasks;
      grid.replaceChildren(...tasks.map(buildMissionCard));
      setSummary(summary);
      document.getElementById("mission-result-count").textContent =
        `${tasks.length} shown`;
      clearBanner.hidden = !(
        summary.total_scheduled > 0 &&
        summary.pending === 0 &&
        summary.skipped === 0 &&
        !hasActiveFilters()
      );
      renderEmptyState(tasks, summary, hasActiveTasks);
    }

    async function loadMissions({ updateUrl = true } = {}) {
      const sequence = ++requestSequence;
      if (activeController) activeController.abort();
      activeController = new AbortController();
      board.setAttribute("aria-busy", "true");
      loadingMessage.hidden = false;
      errorPanel.hidden = true;
      if (updateUrl) syncAddressBar();

      try {
        const response = await fetch(requestUrl(), {
          headers: { Accept: "application/json" },
          credentials: "same-origin",
          signal: activeController.signal,
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "Couldn't load missions.");
        if (sequence !== requestSequence) return;

        renderMissions(payload.tasks, payload.summary, payload.has_active_tasks);
        setSelectedDate(payload.date);
      } catch (error) {
        if (error.name === "AbortError" || sequence !== requestSequence) return;
        grid.replaceChildren();
        emptyPanel.hidden = true;
        clearBanner.hidden = true;
        errorMessage.textContent = error.message || "Network error while loading missions.";
        errorPanel.hidden = false;
      } finally {
        if (sequence === requestSequence) {
          board.setAttribute("aria-busy", "false");
          loadingMessage.hidden = true;
        }
      }
    }

    function setFormErrors(errors, generalMessage = "") {
      formErrors.replaceChildren();
      Object.entries(errors || {}).forEach(([fieldName, messages]) => {
        const container = missionForm.querySelector(`[data-error-for="${fieldName}"]`);
        if (!container) return;
        const values = Array.isArray(messages)
          ? messages.map((message) => typeof message === "string" ? message : message.message)
          : [String(messages)];
        container.textContent = values.join(" ");
      });
      if (generalMessage) {
        formErrors.textContent = generalMessage;
        formErrors.hidden = false;
      } else {
        formErrors.hidden = true;
      }
    }

    function clearFormErrors() {
      setFormErrors({});
      missionForm.querySelectorAll(".mission-field-error").forEach((field) => {
        field.textContent = "";
      });
    }

    function setFormSubmitting(submitting) {
      submitButton.disabled = submitting;
      submitButton.setAttribute("aria-busy", String(submitting));
      submitSpinner.hidden = !submitting;
      submitLabel.textContent = submitting
        ? "SAVING MISSION..."
        : editingTaskId
          ? "SAVE CHANGES"
          : "CREATE MISSION";
    }

    function setCategoryOptionsForEdit(categoryId = null) {
      const categorySelect = missionForm.elements.namedItem("category");
      Array.from(categorySelect.options).forEach((option) => {
        option.disabled =
          option.dataset.active === "false" &&
          (!categoryId || option.value !== String(categoryId));
      });
    }

    function syncRecurrenceFields() {
      const needsWeekdays = ["WEEKLY", "CUSTOM"].includes(recurrenceSelect.value);
      weekdaysField.hidden = !needsWeekdays;
      missionForm.querySelectorAll('input[name="recurrence_days"]').forEach((input) => {
        input.disabled = !needsWeekdays;
        if (!needsWeekdays) input.checked = false;
      });
    }

    function openMissionDialog(task = null) {
      clearFormErrors();
      missionForm.reset();
      keyField.value = creationRequestKey;
      editingTaskId = task ? task.task_id : null;
      setCategoryOptionsForEdit(task ? task.category_id : null);
      document.getElementById("mission-dialog-title").textContent =
        task ? "EDIT MISSION" : "CREATE MISSION";
      submitLabel.textContent = task ? "SAVE CHANGES" : "CREATE MISSION";
      if (task) {
        const values = { ...task, category: task.category_id };
        ["title", "description", "category", "difficulty", "estimated_minutes", "xp_reward", "recurrence_type", "start_date", "end_date"].forEach((name) => {
          const field = missionForm.elements.namedItem(name);
          if (field) field.value = values[name] ?? "";
        });
        const weekdays = new Set((task.recurrence_days || []).map(String));
        missionForm.querySelectorAll('input[name="recurrence_days"]').forEach((input) => {
          input.checked = weekdays.has(input.value);
        });
      } else {
        missionForm.elements.namedItem("start_date").value = dateInput.value;
      }
      syncRecurrenceFields();
      dialog.showModal();
      missionForm.elements.namedItem("title").focus();
    }

    async function postJson(url, payload) {
      const csrfInput = missionForm.querySelector('input[name="csrfmiddlewaretoken"]');
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "X-CSRFToken": csrfInput ? csrfInput.value : "",
        },
        body: payload === undefined ? undefined : JSON.stringify(payload),
      });
      let data = {};
      try {
        data = await response.json();
      } catch {
        throw new Error("The server returned an unreadable response.");
      }
      if (!response.ok) {
        const error = new Error(data.error || "The mission request couldn't be completed.");
        error.status = response.status;
        error.data = data;
        throw error;
      }
      return data;
    }

    async function transitionMission(button, action) {
      const occurrenceId = button.dataset.occurrenceId;
      if (pendingActions.has(occurrenceId)) return;
      pendingActions.add(occurrenceId);
      button.disabled = true;
      try {
        const actionTemplate = {
          complete: config.completeUrlTemplate,
          undo: config.undoUrlTemplate,
          skip: config.skipUrlTemplate,
        }[action];
        await postJson(occurrenceActionUrl(actionTemplate, occurrenceId));
        showToast(
          action === "complete"
            ? "Mission complete. Your progress is saved."
            : action === "undo"
              ? "Mission completion was undone."
              : "Mission marked as skipped."
        );
        await loadMissions({ updateUrl: false });
      } catch (error) {
        showToast(error.message || "Mission update failed. Refreshing saved state.", "error");
        await loadMissions({ updateUrl: false });
      } finally {
        pendingActions.delete(occurrenceId);
      }
    }

    async function archiveMission(button) {
      const taskId =
        button.dataset.taskId ||
        button.closest("[data-task-id]")?.dataset.taskId;
      if (pendingActions.has(`task-${taskId}`)) return;
      if (!window.confirm("Archive this mission? Its completion history will be preserved.")) {
        return;
      }
      pendingActions.add(`task-${taskId}`);
      button.disabled = true;
      try {
        await postJson(taskActionUrl(config.archiveUrlTemplate, taskId));
        showToast("Mission archived. Its history remains preserved.");
        await loadMissions({ updateUrl: false });
      } catch (error) {
        showToast(error.message || "Mission couldn't be archived.", "error");
        await loadMissions({ updateUrl: false });
      } finally {
        pendingActions.delete(`task-${taskId}`);
      }
    }

    function formPayload() {
      const data = new FormData(missionForm);
      const payload = Object.fromEntries(data.entries());
      payload.recurrence_days = data.getAll("recurrence_days").map(Number);
      delete payload.csrfmiddlewaretoken;
      return payload;
    }

    missionForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submitButton.disabled) return;
      clearFormErrors();
      if (!missionForm.reportValidity()) return;

      setFormSubmitting(true);
      const isEditing = Boolean(editingTaskId);
      const url = isEditing
        ? `${taskActionUrl(config.updateUrlTemplate, editingTaskId)}?date=${encodeURIComponent(dateInput.value)}`
        : `${config.createUrl}?date=${encodeURIComponent(dateInput.value)}`;
      try {
        const payload = formPayload();
        if (!isEditing) payload.idempotency_key = creationRequestKey;
        const data = await postJson(url, payload);
        if (!isEditing) {
          creationRequestKey = createIdempotencyKey();
          keyField.value = creationRequestKey;
          try { sessionStorage.setItem(creationKeyStorage, creationRequestKey); } catch (_error) {}
        }
        dialog.close();
        showToast(
          isEditing
            ? "Mission updated."
            : data.scheduled_for_selected_date
              ? "Mission created. Your journey continues."
              : "Mission created. It will appear on its scheduled dates."
        );
        await loadMissions({ updateUrl: true });
      } catch (error) {
        if (error.data && error.data.errors) {
          setFormErrors(error.data.errors);
        } else {
          setFormErrors({}, error.message || "Mission couldn't be saved.");
        }
        await loadMissions({ updateUrl: false });
      } finally {
        setFormSubmitting(false);
      }
    });

    board.addEventListener("click", (event) => {
      const button = event.target.closest("[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      if (action === "edit") {
        event.preventDefault();
        const card = button.closest(".mission-card");
        const taskId = button.dataset.taskId || card?.dataset.taskId;
        const mission = missionTasks.find((task) => String(task.task_id) === String(taskId));
        if (mission) openMissionDialog(mission);
        else showToast("Reload missions before editing this record.", "error");
      } else if (action === "complete" || action === "undo" || action === "skip") {
        transitionMission(button, action);
      } else if (action === "archive" && !button.closest('form[data-action="archive"]')) {
        archiveMission(button);
      }
    });

    board.addEventListener("submit", (event) => {
      const form = event.target.closest('form[data-action="archive"]');
      if (!form) return;
      event.preventDefault();
      archiveMission(form.querySelector('button[type="submit"]') || form);
    });

    document.getElementById("open-mission-dialog").addEventListener("click", () => {
      openMissionDialog();
    });
    document.getElementById("empty-create-mission").addEventListener("click", () => {
      openMissionDialog();
    });
    document.getElementById("close-mission-dialog").addEventListener("click", () => dialog.close());
    document.getElementById("cancel-mission-form").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () => {
      editingTaskId = null;
      setFormSubmitting(false);
      clearFormErrors();
    });
    recurrenceSelect.addEventListener("change", syncRecurrenceFields);

    document.getElementById("mission-previous-day").addEventListener("click", () => {
      dateInput.value = dateByOffset(dateInput.value, -1);
      loadMissions();
    });
    document.getElementById("mission-next-day").addEventListener("click", () => {
      dateInput.value = dateByOffset(dateInput.value, 1);
      loadMissions();
    });
    document.getElementById("mission-today").addEventListener("click", () => {
      dateInput.value = config.today;
      loadMissions();
    });
    dateInput.addEventListener("change", () => loadMissions());
    [statusFilter, categoryFilter, difficultyFilter].forEach((filter) => {
      filter.addEventListener("change", () => loadMissions());
    });
    searchInput.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => loadMissions(), 250);
    });
    document.getElementById("mission-retry").addEventListener("click", () => {
      loadMissions({ updateUrl: false });
    });
    window.addEventListener("popstate", () => {
      const params = new URLSearchParams(window.location.search);
      dateInput.value = params.get("date") || config.today;
      statusFilter.value = params.get("status") || "";
      categoryFilter.value = params.get("category") || "";
      difficultyFilter.value = params.get("difficulty") || "";
      searchInput.value = params.get("search") || "";
      loadMissions({ updateUrl: false });
    });

    loadMissions({ updateUrl: false });
  }

  function initialize() {
    initializeNavigation();
    initializeMissionBoard();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
