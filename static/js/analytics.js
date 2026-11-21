(() => {
  const configElement = document.getElementById("analytics-config");
  const page = document.getElementById("analytics-page");
  if (!configElement || !page) return;

  const config = JSON.parse(configElement.textContent);
  const numberFormat = new Intl.NumberFormat();
  const svgNamespace = "http://www.w3.org/2000/svg";
  const loading = document.getElementById("analytics-loading");
  const errorPanel = document.getElementById("analytics-error");
  const errorMessage = document.getElementById("analytics-error-message");
  const dateInput = document.getElementById("analytics-date");
  let dateRequest = 0;
  let trendRequest = 0;
  let comparisonRequest = 0;

  const number = (value) => (
    value === null || value === undefined ? "—" : numberFormat.format(value)
  );
  const percentage = (value) => (
    value === null || value === undefined ? "—" : `${number(value)}%`
  );
  const byId = (id) => document.getElementById(id);

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = value;
  }

  function setHidden(id, hidden) {
    const element = byId(id);
    if (element) element.hidden = hidden;
  }

  function formatDate(value, options = { month: "short", day: "numeric" }) {
    if (!value) return "—";
    const [year, month, day] = value.split("-").map(Number);
    return new Intl.DateTimeFormat(undefined, options).format(
      new Date(year, month - 1, day),
    );
  }

  function formatPeriod(start, end) {
    if (!start || !end) return "No period data";
    if (start === end) return formatDate(start, { month: "short", day: "numeric", year: "numeric" });
    return `${formatDate(start)} – ${formatDate(end, { month: "short", day: "numeric", year: "numeric" })}`;
  }

  async function fetchJSON(url) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error("The analytics service returned an unreadable response.");
    }
    if (!response.ok) {
      throw new Error(payload.error || "Analytics data could not be loaded.");
    }
    return payload;
  }

  function showError(error) {
    errorMessage.textContent = error.message || "Analytics data could not be loaded.";
    errorPanel.hidden = false;
    loading.hidden = true;
  }

  function setProgress(elementId, value) {
    const element = byId(elementId);
    if (!element) return;
    const safeValue = Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
    element.style.width = `${safeValue}%`;
  }

  function renderOverview(overview) {
    setText("metric-missions", number(overview.scheduled_missions));
    setText("metric-missions-note", `${number(overview.missions_created)} mission definitions`);
    setText("metric-completed", number(overview.completed_missions));
    setText("metric-completion-rate", percentage(overview.completion_rate));
    setText(
      "metric-completion-note",
      overview.completion_rate === null
        ? "No scheduled occurrences recorded"
        : `${number(overview.pending_missions)} pending · ${number(overview.skipped_missions)} skipped`,
    );
    setText("metric-xp", number(overview.total_xp_balance));
    setText(
      "metric-xp-note",
      `${number(overview.lifetime_xp_earned)} earned · ${number(overview.lifetime_xp_reversed)} reversed`,
    );
    setText("metric-streak", `${number(overview.current_streak)} days`);
    setText("metric-longest-streak", `Longest streak ${number(overview.longest_streak)} days`);
    setText("metric-achievements", number(overview.unlocked_achievements));
  }

  function renderDaily(day) {
    dateInput.value = day.date;
    setText("daily-readable-date", formatDate(day.date, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    }));
    setText("daily-completed", number(day.completed));
    setText("daily-scheduled", number(day.scheduled_missions));
    setText("daily-pending", number(day.pending));
    setText("daily-skipped", number(day.skipped));
    setText("daily-rate", percentage(day.completion_rate));
    setProgress("daily-progress", day.completion_rate);
    setHidden("daily-empty", !(day.available && day.scheduled_missions === 0));
    if (!day.available) {
      setText("daily-readable-date", "Future dates have no recorded analytics.");
      setHidden("daily-empty", false);
    }
    const next = document.querySelector('[data-date-shift="1"]');
    if (next) next.disabled = dateInput.value >= config.today;
  }

  function listItem(label, completed, scheduled, rate, options = {}) {
    const row = document.createElement("div");
    row.className = "analytics-day-row";

    const date = document.createElement("span");
    date.className = "analytics-day-name";
    date.textContent = label;

    const track = document.createElement("span");
    track.className = "analytics-mini-track";
    const fill = document.createElement("span");
    fill.style.width = `${rate === null || rate === undefined ? 0 : Math.min(100, Math.max(0, rate))}%`;
    if (options.future) fill.className = "is-unavailable";
    track.append(fill);

    const value = document.createElement("span");
    value.className = "analytics-day-value";
    value.textContent = options.future
      ? "FUTURE"
      : `${number(completed)} / ${number(scheduled)}`;

    row.append(date, track, value);
    return row;
  }

  function renderWeekly(weekly) {
    const daysContainer = byId("weekly-days");
    daysContainer.replaceChildren();
    const first = weekly.days[0]?.date;
    const last = weekly.days[weekly.days.length - 1]?.date;
    setText("weekly-period-label", `WEEK OF ${formatDate(first, { month: "short", day: "numeric" })}`);
    setText("weekly-rate", percentage(weekly.completion_rate));
    for (const day of weekly.days) {
      daysContainer.append(
        listItem(
          formatDate(day.date, { weekday: "short" }),
          day.completed,
          day.scheduled_missions,
          day.completion_rate,
          { future: !day.available },
        ),
      );
    }
    setText(
      "weekly-best",
      weekly.best_day
        ? `${formatDate(weekly.best_day.date, { weekday: "short", month: "short", day: "numeric" })} · ${percentage(weekly.best_day.completion_rate)}`
        : "No recorded day",
    );
    setText(
      "weekly-weakest",
      weekly.weakest_day
        ? `${formatDate(weekly.weakest_day.date, { weekday: "short", month: "short", day: "numeric" })} · ${percentage(weekly.weakest_day.completion_rate)}`
        : "No recorded day",
    );
    setHidden("weekly-empty", weekly.scheduled_missions !== 0);
  }

  function renderMonthly(monthly) {
    const monthStart = monthly.period_start;
    setText("monthly-label", monthStart
      ? formatDate(monthStart, { month: "long", year: "numeric" })
      : "No period data");
    setText("monthly-rate", percentage(monthly.completion_rate));
    setText("monthly-completed", number(monthly.completed));
    setText("monthly-scheduled", number(monthly.scheduled_missions));
    setText("monthly-active-days", number(monthly.active_days));
    setText("monthly-xp", number(monthly.xp_net));

    const weeks = byId("monthly-weeks");
    weeks.replaceChildren();
    for (const week of monthly.weeks) {
      weeks.append(
        listItem(
          `${formatDate(week.period_start)} – ${formatDate(week.period_end)}`,
          week.completed,
          week.scheduled_missions,
          week.completion_rate,
          { future: !week.available },
        ),
      );
    }
    setHidden("monthly-empty", monthly.scheduled_missions !== 0);
  }

  function renderConsistency(consistency) {
    setText("consistency-active", number(consistency.active_days));
    setText("consistency-rate", percentage(consistency.consistency_rate));
    const days = byId("consistency-days");
    days.replaceChildren();
    for (const day of consistency.daily) {
      const marker = document.createElement("span");
      marker.className = "analytics-streak-day";
      marker.classList.toggle("is-active", day.active === true);
      marker.classList.toggle("is-future", !day.available);
      marker.title = `${formatDate(day.date, { month: "short", day: "numeric" })}: ${
        !day.available ? "future" : day.active ? "active" : "no qualifying completion recorded"
      }`;
      marker.setAttribute("aria-label", marker.title);
      days.append(marker);
    }
    setText(
      "consistency-note",
      consistency.data_available
        ? `${number(consistency.current_streak)} current · ${number(consistency.longest_streak)} longest streak`
        : "No streak or occurrence records establish a consistency rate for this window.",
    );
  }

  function renderBreakdown(targetId, items, kind) {
    const container = byId(targetId);
    container.replaceChildren();
    for (const item of items) {
      const name = kind === "difficulty" ? item.label : item.category;
      const row = document.createElement("article");
      row.className = `analytics-breakdown-row${item.data_available ? "" : " has-no-data"}`;
      const heading = document.createElement("div");
      heading.className = "analytics-breakdown-heading";
      const title = document.createElement("strong");
      title.textContent = name;
      const percentageValue = document.createElement("span");
      percentageValue.textContent = item.data_available
        ? percentage(item.completion_rate)
        : "NO DATA";
      heading.append(title, percentageValue);

      const track = document.createElement("span");
      track.className = "analytics-mini-track";
      const fill = document.createElement("span");
      fill.style.width = `${item.completion_rate ?? 0}%`;
      track.append(fill);

      const details = document.createElement("small");
      const xp = item.xp_net;
      details.textContent = item.data_available
        ? `${number(item.completed)} / ${number(item.scheduled_missions)} missions · ${number(xp)} net XP`
        : "No occurrence or mission XP records";
      row.append(heading, track, details);
      container.append(row);
    }
  }

  function renderCategories(data) {
    const activeCount = data.categories.filter((item) => item.scheduled_missions > 0).length;
    setText("category-count", `${number(activeCount)} TRACKED`);
    renderBreakdown("category-breakdown", data.categories, "category");
    setHidden("category-empty", data.data_available);
  }

  function renderDifficulty(data) {
    const activeCount = data.difficulties.filter((item) => item.scheduled_missions > 0).length;
    setText("difficulty-count", `${number(activeCount)} TRACKED`);
    renderBreakdown("difficulty-breakdown", data.difficulties, "difficulty");
    setHidden("difficulty-empty", data.data_available);
  }

  function renderComparison(comparison) {
    const message = byId("comparison-message");
    if (!comparison.available) {
      message.textContent = !comparison.previous_period_available
        ? "Previous-period activity is not recorded; changes are unavailable rather than shown as zero."
        : "Both periods do not contain comparable recorded activity.";
      setText("comparison-completed", "—");
      setText("comparison-rate", "—");
      setText("comparison-xp", "—");
      setText("comparison-consistency", "—");
      return;
    }
    message.textContent = `${formatPeriod(
      comparison.current.period_start,
      comparison.current.period_end,
    )} compared with ${formatPeriod(
      comparison.previous.period_start,
      comparison.previous.period_end,
    )}`;
    const changes = comparison.changes;
    setText(
      "comparison-completed",
      changes.completed_missions === null ? "—" : `${changes.completed_missions > 0 ? "+" : ""}${number(changes.completed_missions)}`,
    );
    setText(
      "comparison-rate",
      changes.completion_rate_points === null
        ? "—"
        : `${changes.completion_rate_points > 0 ? "+" : ""}${number(changes.completion_rate_points)} pp`,
    );
    setText(
      "comparison-xp",
      changes.xp_net === null ? "—" : `${changes.xp_net > 0 ? "+" : ""}${number(changes.xp_net)} XP`,
    );
    setText(
      "comparison-consistency",
      changes.consistency_points === null
        ? "—"
        : `${changes.consistency_points > 0 ? "+" : ""}${number(changes.consistency_points)} pp`,
    );
  }

  function renderInsights(insights) {
    const container = byId("analytics-insights");
    container.replaceChildren();
    for (const insight of insights) {
      const card = document.createElement("article");
      card.className = `analytics-insight insight-${insight.type.toLowerCase()}`;
      const type = document.createElement("span");
      type.className = "analytics-insight-type";
      type.textContent = insight.type.replaceAll("_", " ");
      const title = document.createElement("h3");
      title.textContent = insight.title;
      const description = document.createElement("p");
      description.textContent = insight.description;
      const detail = document.createElement("small");
      const metricValue = insight.metric?.value;
      detail.textContent = metricValue === null || metricValue === undefined
        ? insight.period.replaceAll("_", " ")
        : `${number(metricValue)} ${insight.metric.unit || ""} · ${insight.period.replaceAll("_", " ")}`;
      card.append(type, title, description, detail);
      container.append(card);
    }
    setHidden("insights-empty", insights.length > 0);
  }

  function createSvgElement(tag, attributes = {}) {
    const element = document.createElementNS(svgNamespace, tag);
    for (const [name, value] of Object.entries(attributes)) {
      element.setAttribute(name, String(value));
    }
    return element;
  }

  function renderLineChart(containerId, points, series, options = {}) {
    const container = byId(containerId);
    container.replaceChildren();
    const hasValues = points.some((point) =>
      series.some((item) => Number.isFinite(point[item.key])),
    );
    if (!points.length || !hasValues) {
      container.textContent = "No recorded data";
      return;
    }

    const width = 300;
    const height = 150;
    const padding = { top: 10, right: 7, bottom: 24, left: 28 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const values = points.flatMap((point) =>
      series.map((item) => point[item.key]).filter(Number.isFinite),
    );
    let minValue = options.minimum ?? Math.min(...values);
    let maxValue = options.maximum ?? Math.max(...values);
    if (minValue === maxValue) {
      if (options.minimum === undefined) minValue = Math.min(0, minValue);
      if (options.maximum === undefined) maxValue += 1;
    }
    if (options.includeZero) {
      minValue = Math.min(0, minValue);
      maxValue = Math.max(0, maxValue);
    }
    const span = maxValue - minValue || 1;
    const x = (index) => padding.left + (
      points.length < 2 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth
    );
    const y = (value) => padding.top + ((maxValue - value) / span) * plotHeight;
    const svg = createSvgElement("svg", {
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-label": options.label,
      preserveAspectRatio: "none",
    });

    for (let index = 0; index < 3; index += 1) {
      const gridY = padding.top + (plotHeight * index) / 2;
      svg.append(createSvgElement("line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: gridY,
        y2: gridY,
        class: "analytics-chart-gridline",
      }));
      const axisValue = maxValue - (span * index) / 2;
      const label = createSvgElement("text", {
        x: padding.left - 5,
        y: gridY + 3,
        "text-anchor": "end",
        class: "analytics-chart-axis",
      });
      label.textContent = number(Math.round(axisValue));
      svg.append(label);
    }
    if (minValue < 0 && maxValue > 0) {
      svg.append(createSvgElement("line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: y(0),
        y2: y(0),
        class: "analytics-chart-zero",
      }));
    }

    for (const item of series) {
      let pathData = "";
      let penDown = false;
      points.forEach((point, index) => {
        const value = point[item.key];
        if (!Number.isFinite(value)) {
          penDown = false;
          return;
        }
        pathData += `${penDown ? "L" : "M"}${x(index)} ${y(value)} `;
        penDown = true;
      });
      if (pathData) {
        const path = createSvgElement("path", {
          d: pathData.trim(),
          class: item.className,
          fill: "none",
        });
        const title = createSvgElement("title");
        title.textContent = item.label;
        path.append(title);
        svg.append(path);
      }
      points.forEach((point, index) => {
        const value = point[item.key];
        if (!Number.isFinite(value)) return;
        const marker = createSvgElement("circle", {
          cx: x(index),
          cy: y(value),
          r: 2,
          class: item.pointClass,
        });
        const title = createSvgElement("title");
        title.textContent = `${formatDate(point.date)}: ${number(value)} ${item.unit || ""}`;
        marker.append(title);
        svg.append(marker);
      });
    }

    const startLabel = createSvgElement("text", {
      x: padding.left,
      y: height - 5,
      class: "analytics-chart-axis",
    });
    startLabel.textContent = formatDate(points[0].date);
    const endLabel = createSvgElement("text", {
      x: width - padding.right,
      y: height - 5,
      "text-anchor": "end",
      class: "analytics-chart-axis",
    });
    endLabel.textContent = formatDate(points[points.length - 1].date);
    svg.append(startLabel, endLabel);
    container.append(svg);
  }

  function renderTrends(trends) {
    const points = trends.points;
    const hasMissions = points.some((point) => point.scheduled > 0);
    const hasXp = points.some((point) =>
      (Number.isFinite(point.xp_earned) && point.xp_earned !== 0)
      || (Number.isFinite(point.xp_reversed) && point.xp_reversed !== 0)
      || (Number.isFinite(point.xp_net) && point.xp_net !== 0),
    );
    renderLineChart(
      "missions-trend-chart",
      hasMissions ? points : [],
      [
        { key: "completed", className: "chart-series-violet", pointClass: "chart-point-violet", label: "Completed missions", unit: "missions" },
        { key: "scheduled", className: "chart-series-muted", pointClass: "chart-point-muted", label: "Scheduled missions", unit: "missions" },
      ],
      { minimum: 0, label: "Daily completed and scheduled missions" },
    );
    renderLineChart(
      "xp-trend-chart",
      hasXp ? points : [],
      [{ key: "xp_net", className: "chart-series-cyan", pointClass: "chart-point-cyan", label: "Net XP", unit: "XP" }],
      { includeZero: true, label: "Daily net XP" },
    );
    renderLineChart(
      "completion-trend-chart",
      points,
      [{ key: "completion_rate", className: "chart-series-green", pointClass: "chart-point-green", label: "Completion rate", unit: "%" }],
      { minimum: 0, maximum: 100, label: "Daily mission completion rate" },
    );
    const hasTrend = hasMissions || hasXp;
    setHidden("trend-empty", hasTrend);
    if (!hasTrend) {
      byId("missions-trend-chart").textContent = "No occurrence data";
      byId("xp-trend-chart").textContent = "No XP ledger data";
      byId("completion-trend-chart").textContent = "No completion-rate data";
    }
  }

  function renderDashboard(data) {
    renderOverview(data.overview);
    renderDaily(data.daily);
    renderWeekly(data.weekly);
    renderMonthly(data.monthly);
    renderConsistency(data.consistency);
    renderCategories(data.categories);
    renderDifficulty(data.difficulty);
    renderComparison(data.comparisons.week);
    renderInsights(data.insights);
    renderTrends(data.trends);
    loading.hidden = true;
    errorPanel.hidden = true;
  }

  async function loadDashboard() {
    loading.hidden = false;
    errorPanel.hidden = true;
    try {
      renderDashboard(await fetchJSON(config.urls.dashboard));
    } catch (error) {
      showError(error);
    }
  }

  async function loadSelectedDate() {
    const selectedDate = dateInput.value;
    if (!selectedDate) return;
    if (selectedDate > config.today) {
      dateInput.value = config.today;
      return;
    }
    const currentRequest = ++dateRequest;
    const query = `?date=${encodeURIComponent(selectedDate)}`;
    try {
      const [daily, weekly, monthly] = await Promise.all([
        fetchJSON(`${config.urls.daily}${query}`),
        fetchJSON(`${config.urls.weekly}${query}`),
        fetchJSON(`${config.urls.monthly}${query}`),
      ]);
      if (currentRequest !== dateRequest) return;
      renderDaily(daily);
      renderWeekly(weekly);
      renderMonthly(monthly);
    } catch (error) {
      if (currentRequest === dateRequest) showError(error);
    }
  }

  async function loadTrendRange() {
    const currentRequest = ++trendRequest;
    try {
      const range = document.getElementById("trend-range").value;
      const trends = await fetchJSON(`${config.urls.trends}?range=${encodeURIComponent(range)}`);
      if (currentRequest === trendRequest) renderTrends(trends);
    } catch (error) {
      if (currentRequest === trendRequest) showError(error);
    }
  }

  async function loadComparison(period) {
    const currentRequest = ++comparisonRequest;
    try {
      const comparison = await fetchJSON(
        `${config.urls.comparison}?period=${encodeURIComponent(period)}`,
      );
      if (currentRequest === comparisonRequest) renderComparison(comparison);
    } catch (error) {
      if (currentRequest === comparisonRequest) showError(error);
    }
  }

  document.querySelectorAll("[data-date-shift]").forEach((button) => {
    button.addEventListener("click", () => {
      const [year, month, day] = dateInput.value.split("-").map(Number);
      const shifted = new Date(year, month - 1, day);
      shifted.setDate(shifted.getDate() + Number(button.dataset.dateShift));
      const nextDate = [
        shifted.getFullYear(),
        String(shifted.getMonth() + 1).padStart(2, "0"),
        String(shifted.getDate()).padStart(2, "0"),
      ].join("-");
      if (nextDate <= config.today) {
        dateInput.value = nextDate;
        loadSelectedDate();
      }
    });
  });
  dateInput.addEventListener("change", loadSelectedDate);
  byId("analytics-today").addEventListener("click", () => {
    dateInput.value = config.today;
    loadSelectedDate();
  });
  document.getElementById("trend-range").addEventListener("change", loadTrendRange);
  document.getElementById("comparison-period").addEventListener("change", (event) => {
    loadComparison(event.target.value);
  });
  byId("analytics-retry").addEventListener("click", loadDashboard);

  loadDashboard();
})();
