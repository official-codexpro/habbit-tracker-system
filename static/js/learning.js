(() => {
  const page = document.getElementById("learning-page");
  const configElement = document.getElementById("learning-config");
  if (!page || !configElement) return;
  const config = JSON.parse(configElement.textContent);
  const modal = document.getElementById("learning-modal");
  const modalTitle = document.getElementById("learning-modal-title");
  const modalContent = document.getElementById("learning-modal-content");
  const loading = document.getElementById("learning-loading");
  const errorPanel = document.getElementById("learning-error");
  const errorMessage = document.getElementById("learning-error-message");

  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        ...(options.headers || {}),
      },
      ...options,
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error("The learning service returned an unreadable response.");
    }
    if (!response.ok) {
      if (payload.errors) {
        const messages = [];
        Object.entries(payload.errors).forEach(([field, errors]) => {
          errors.forEach((error) => messages.push(`${field}: ${error.message}`));
        });
        throw new Error(messages.join(" "));
      }
      throw new Error(payload.error || "The learning operation could not be completed.");
    }
    return payload;
  }

  function showError(error) {
    errorMessage.textContent = error.message || "Learning data could not be loaded.";
    errorPanel.hidden = false;
    loading.hidden = true;
  }

  function formatDuration(minutes) {
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return hours ? `${hours}h ${remainder}m` : `${remainder}m`;
  }

  function escapeText(value) {
    const span = document.createElement("span");
    span.textContent = value ?? "";
    return span.innerHTML;
  }

  function closeModal() {
    modal.hidden = true;
    document.body.classList.remove("menu-open");
  }

  function openModal(title, formHtml, submitLabel, submitHandler) {
    modalTitle.textContent = title;
    modalContent.innerHTML = formHtml;
    modal.hidden = false;
    document.body.classList.remove("menu-open");
    modal.querySelector("input, select, textarea")?.focus();
    const form = modalContent.querySelector("form");
    form.querySelector("[type=submit]").textContent = submitLabel;
  }

  function formShell(fields, submitLabel = "SAVE") {
    return `<form class="learning-form" novalidate>${fields}<p class="learning-form-error" data-form-error hidden></p><div class="learning-form-actions"><button type="button" data-close-modal>CANCEL</button><button type="submit">${submitLabel}</button></div></form>`;
  }

  function optionItems(items, selectedId = "") {
    return items.map((item) =>
      `<option value="${item.id}" ${String(item.id) === String(selectedId) ? "selected" : ""}>${escapeText(item.name || item.title)}</option>`
    ).join("");
  }

  async function loadDashboard() {
    loading.hidden = false;
    errorPanel.hidden = true;
    try {
      const data = await request(config.dashboardUrl);
      document.getElementById("learning-goals-count").textContent = data.active_goals_count;
      document.getElementById("learning-skills-count").textContent = data.skills_count;
      document.getElementById("learning-courses-count").textContent = data.courses_count;
      document.getElementById("learning-completed-courses").textContent = data.completed_courses_count;
      document.getElementById("learning-total-time").textContent = formatDuration(data.total_minutes);
      document.getElementById("learning-time-detail").textContent = `${data.total_minutes} recorded minutes`;
      document.getElementById("learning-session-count").textContent = data.session_count;

      const goalsList = document.getElementById("learning-goals-list");
      goalsList.innerHTML = data.active_learning_goals.length
        ? data.active_learning_goals.map((goal) => `
          <article class="learning-goal-card">
            <div><span class="learning-priority priority-${goal.priority}">P${goal.priority}</span><strong>${escapeText(goal.title)}</strong></div>
            <p>${escapeText(goal.description || "No description recorded.")}</p>
            <small>${goal.target_date ? `TARGET ${goal.target_date}` : "NO TARGET DATE"} · ${goal.status_label}</small>
          </article>`).join("")
        : '<p class="learning-empty">No learning goals recorded yet.</p>';

      const skillsList = document.getElementById("learning-skills-list");
      skillsList.innerHTML = data.skills.length
        ? data.skills.map((skill) => `
          <article class="learning-skill-card">
            <div><strong>${escapeText(skill.name)}</strong><span>Level ${skill.current_proficiency} → ${skill.target_proficiency}</span></div>
            <div class="learning-proficiency-track"><span style="width:${skill.current_proficiency * 20}%"></span></div>
            <small>${escapeText(skill.category || "GENERAL")} · ${skill.status_label}</small>
          </article>`).join("")
        : '<p class="learning-empty">No skills discovered yet.</p>';

      const coursesList = document.getElementById("learning-courses-list");
      coursesList.innerHTML = data.active_courses.length
        ? data.active_courses.map((course) => `
          <article class="learning-course-card">
            <div><strong>${escapeText(course.title)}</strong><span>${course.status_label}</span></div>
            <div class="learning-progress-track"><span style="width:${course.progress_percentage ?? 0}%"></span></div>
            <small>${course.progress_percentage === null ? "Progress unavailable until topics and total are defined" : `${course.completed_topics} / ${course.total_topics} topics · ${course.progress_percentage}%`}</small>
          </article>`).join("")
        : '<p class="learning-empty">No courses recorded yet.</p>';

      const sessionsList = document.getElementById("learning-sessions-list");
      sessionsList.innerHTML = data.recent_sessions.length
        ? data.recent_sessions.map((session) => `
          <article class="learning-session-row">
            <span class="learning-session-date">${escapeText(session.session_date)}</span>
            <div><strong>${escapeText(session.title)}</strong><small>${escapeText(session.course || session.skill || "Independent practice")}</small></div>
            <strong class="learning-duration">${formatDuration(session.duration_minutes)}</strong>
          </article>`).join("")
        : '<p class="learning-empty">No learning sessions recorded yet.</p>';

      const consistency = document.getElementById("learning-consistency-days");
      consistency.innerHTML = "";
      const today = new Date(`${config.today}T12:00:00`);
      const active = new Set(data.consistency_dates);
      for (let index = 29; index >= 0; index -= 1) {
        const date = new Date(today);
        date.setDate(today.getDate() - index);
        const iso = [
          date.getFullYear(),
          String(date.getMonth() + 1).padStart(2, "0"),
          String(date.getDate()).padStart(2, "0"),
        ].join("-");
        const marker = document.createElement("span");
        marker.className = "learning-consistency-day";
        marker.classList.toggle("is-active", active.has(iso));
        marker.title = `${iso}: ${active.has(iso) ? "learning session recorded" : "no learning session recorded"}`;
        consistency.append(marker);
      }
      document.getElementById("learning-consistency-badge").textContent = `${active.size} DAYS`;
      loading.hidden = true;
      errorPanel.hidden = true;
    } catch (error) {
      showError(error);
    }
  }

  async function openGoalModal() {
    openModal(
      "ADD LEARNING GOAL",
      formShell(`
        <label class="full">MISSION TITLE<input name="title" maxlength="200" required></label>
        <label class="full">DESCRIPTION<textarea name="description" rows="3"></textarea></label>
        <label>TARGET DATE<input name="target_date" type="date"></label>
        <label>PRIORITY<select name="priority"><option value="1">1 · Low</option><option value="2" selected>2 · Normal</option><option value="3">3 · High</option><option value="4">4 · Critical</option></select></label>
        <input type="hidden" name="status" value="ACTIVE">
      `),
      "CREATE GOAL",
    );
  }

  async function openSkillModal() {
    const [goalsResponse] = await Promise.all([
      request(config.goalsUrl),
    ]);
    openModal(
      "ADD SKILL",
      formShell(`
        <label class="full">SKILL NAME<input name="name" maxlength="120" required></label>
        <label class="full">DESCRIPTION<textarea name="description" rows="3"></textarea></label>
        <label>CATEGORY<input name="category" maxlength="80"></label>
        <label>CURRENT LEVEL<select name="current_proficiency">${[1,2,3,4,5].map((value) => `<option value="${value}">${value}</option>`).join("")}</select></label>
        <label>TARGET LEVEL<select name="target_proficiency">${[1,2,3,4,5].map((value) => `<option value="${value}" ${value === 5 ? "selected" : ""}>${value}</option>`).join("")}</select></label>
        <label class="full">RELATED GOALS<select name="learning_goals" multiple>${optionItems(goalsResponse.goals)}</select></label>
        <input type="hidden" name="status" value="ACTIVE">
      `),
      "CREATE SKILL",
    );
  }

  async function openCourseModal() {
    const [goalsResponse, skillsResponse] = await Promise.all([
      request(config.goalsUrl),
      request(config.skillsUrl),
    ]);
    openModal(
      "ADD COURSE",
      formShell(`
        <label class="full">COURSE TITLE<input name="title" maxlength="200" required></label>
        <label class="full">DESCRIPTION<textarea name="description" rows="3"></textarea></label>
        <label>RELATED SKILL<select name="skill"><option value="">No skill selected</option>${optionItems(skillsResponse.skills)}</select></label>
        <label>RELATED GOAL<select name="learning_goal"><option value="">No goal selected</option>${optionItems(goalsResponse.goals)}</select></label>
        <label>PROVIDER<input name="provider" maxlength="200"></label>
        <label>RESOURCE URL<input name="resource_url" type="url"></label>
        <label>TOTAL TOPICS<input name="total_topics" type="number" min="0"></label>
        <label>COMPLETED TOPICS<input name="completed_topics" type="number" min="0" value="0"></label>
        <label>START DATE<input name="start_date" type="date" value="${config.today}" required></label>
        <label>TARGET DATE<input name="target_completion_date" type="date"></label>
        <input type="hidden" name="status" value="NOT_STARTED">
      `),
      "CREATE COURSE",
    );
  }

  async function openSessionModal() {
    const [coursesResponse, skillsResponse, goalsResponse] = await Promise.all([
      request(config.coursesUrl),
      request(config.skillsUrl),
      request(config.goalsUrl),
    ]);
    openModal(
      "RECORD LEARNING SESSION",
      formShell(`
        <label class="full">SESSION TITLE<input name="title" maxlength="200" required></label>
        <label>COURSE<select name="course"><option value="">Independent / no course</option>${optionItems(coursesResponse.courses)}</select></label>
        <label>SKILL<select name="skill"><option value="">No skill selected</option>${optionItems(skillsResponse.skills)}</select></label>
        <label>LEARNING GOAL<select name="learning_goal"><option value="">No goal selected</option>${optionItems(goalsResponse.goals)}</select></label>
        <label>DURATION (MINUTES)<input name="duration_minutes" type="number" min="1" required></label>
        <label>SESSION DATE<input name="session_date" type="date" value="${config.today}" max="${config.today}" required></label>
        <label class="full">TOPICS COVERED<textarea name="topics_covered" rows="2"></textarea></label>
        <label class="full">NOTES<textarea name="notes" rows="3"></textarea></label>
      `),
      "SAVE SESSION",
    );
  }

  modalContent.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    const formData = new FormData(form);
    const payload = {};
    formData.forEach((value, key) => {
      if (key === "learning_goals") {
        payload[key] = payload[key] || [];
        payload[key].push(Number(value));
      } else if (["priority", "current_proficiency", "target_proficiency", "duration_minutes", "total_topics", "completed_topics", "skill", "learning_goal", "course"].includes(key)) {
        payload[key] = value === "" ? null : Number(value);
      } else {
        payload[key] = value === "" ? null : value;
      }
    });
    let url = null;
    if (modalTitle.textContent === "ADD LEARNING GOAL") url = config.goalsUrl;
    if (modalTitle.textContent === "ADD SKILL") url = config.skillsUrl;
    if (modalTitle.textContent === "ADD COURSE") url = config.coursesUrl;
    if (modalTitle.textContent === "RECORD LEARNING SESSION") url = config.sessionsUrl;
    try {
      await request(url, { method: "POST", body: JSON.stringify(payload) });
      closeModal();
      await loadDashboard();
    } catch (error) {
      const message = form.querySelector("[data-form-error]");
      message.textContent = error.message;
      message.hidden = false;
      submit.disabled = false;
    }
  });

  document.querySelectorAll("[data-open-modal]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.openModal === "goal") openGoalModal();
      if (button.dataset.openModal === "skill") openSkillModal();
      if (button.dataset.openModal === "course") openCourseModal();
      if (button.dataset.openModal === "session") openSessionModal();
    });
  });
  document.querySelectorAll("[data-close-modal]").forEach((element) => {
    element.addEventListener("click", closeModal);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) closeModal();
  });
  document.getElementById("learning-retry").addEventListener("click", loadDashboard);

  loadDashboard();
})();
