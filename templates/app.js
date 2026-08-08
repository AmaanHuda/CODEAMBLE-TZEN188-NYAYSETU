(() => {
  const API_BASE = window.location.origin;

  const screens = {
    upload: document.getElementById("upload-screen"),
    processing: document.getElementById("processing-screen"),
    ooc: document.getElementById("ooc-screen"),
    error: document.getElementById("error-screen"),
    results: document.getElementById("results-screen"),
  };

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const uploadError = document.getElementById("upload-error");
  const startOverBtn = document.getElementById("start-over-btn");
  const oocRetryBtn = document.getElementById("ooc-retry-btn");
  const errorRetryBtn = document.getElementById("error-retry-btn");

  const ALLOWED_EXT = [".pdf", ".docx", ".txt"];
  const MAX_MB = 15;

  let stageTimer = null;

  function showScreen(name) {
    Object.values(screens).forEach((s) => (s.hidden = true));
    screens[name].hidden = false;
    startOverBtn.hidden = name === "upload";
  }

  function showUploadError(msg) {
    uploadError.textContent = msg;
    uploadError.hidden = false;
  }

  function clearUploadError() {
    uploadError.hidden = true;
    uploadError.textContent = "";
  }

  function validateFile(file) {
    const name = file.name.toLowerCase();
    const ext = "." + name.split(".").pop();
    if (!ALLOWED_EXT.includes(ext)) {
      return `"${file.name}" isn't a supported file type. Please upload a PDF, DOCX, or TXT file.`;
    }
    if (file.size === 0) {
      return `"${file.name}" is empty.`;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      return `"${file.name}" is larger than the ${MAX_MB}MB limit.`;
    }
    return null;
  }

  // ---------- Processing stage animation ----------
  const stages = [
    "reading",
    "checking",
    "extracting",
    "deadlines",
    "clauses",
    "preparing",
  ];

  function runStageAnimation() {
    const items = document.querySelectorAll("#stage-list li");
    items.forEach((i) => i.classList.remove("active", "done"));
    let idx = 0;
    items[0].classList.add("active");

    clearInterval(stageTimer);
    stageTimer = setInterval(() => {
      items[idx].classList.remove("active");
      items[idx].classList.add("done");
      idx++;
      if (idx < items.length) {
        items[idx].classList.add("active");
      } else {
        clearInterval(stageTimer);
      }
    }, 1100);
  }

  // ---------- Upload flow ----------
  async function handleFile(file) {
    clearUploadError();
    const validationError = validateFile(file);
    if (validationError) {
      showUploadError(validationError);
      return;
    }

    document.getElementById("processing-filename").textContent =
      `Reading "${file.name}"…`;
    showScreen("processing");
    runStageAnimation();

    const formData = new FormData();
    formData.append("file", file);

    try {
      const resp = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      clearInterval(stageTimer);
      handleResult(data);
    } catch (err) {
      clearInterval(stageTimer);
      showError(
        "We couldn't reach the server. Check your connection and try again.",
      );
    }
  }

  // classification -> { css class, label, icon, heading }
  const CLASSIFICATION_META = {
    LEGAL: {
      css: "legal",
      label: "Legal document",
      icon: "✓",
      heading: "Legal document",
    },
    NON_LEGAL: {
      css: "non-legal",
      label: "Not a legal document",
      icon: "✕",
      heading: "Not a legal document",
    },
    UNCERTAIN: {
      css: "uncertain",
      label: "Not sure",
      icon: "?",
      heading: "Not sure",
    },
  };

  function setBadge(badgeEl, classification) {
    const meta =
      CLASSIFICATION_META[classification] || CLASSIFICATION_META.NON_LEGAL;
    badgeEl.className = `classification-badge ${meta.css}`;
    badgeEl.querySelector(".classification-label").textContent = meta.label;
    return meta;
  }

  function handleResult(data) {
    if (!data || !data.status) {
      showError("The server returned an unexpected response.");
      return;
    }
    if (data.status === "OUT_OF_CONTEXT") {
      const classification = data.classification || "NON_LEGAL";
      const meta = setBadge(
        document.getElementById("ooc-classification-badge"),
        classification,
      );
      document.getElementById("ooc-icon").textContent = meta.icon;
      document
        .getElementById("ooc-icon")
        .classList.toggle("error", classification === "NON_LEGAL");
      document.getElementById("ooc-heading").textContent = meta.heading;
      document.getElementById("ooc-message").textContent =
        data.message || "This document does not appear to be legal in nature.";
      showScreen("ooc");
      return;
    }
    if (data.status === "ERROR") {
      showError(data.message || "Something went wrong.");
      return;
    }
    if (data.status === "ANALYZED") {
      setBadge(
        document.getElementById("results-classification-badge"),
        data.classification || "LEGAL",
      );
      renderResults(data);
      showScreen("results");
      return;
    }
    showError("The server returned an unrecognized response.");
  }

  function showError(msg) {
    document.getElementById("error-message").textContent = msg;
    showScreen("error");
  }

  // ---------- Results rendering ----------
  function el(tag, opts = {}) {
    const node = document.createElement(tag);
    if (opts.className) node.className = opts.className;
    if (opts.text) node.textContent = opts.text;
    if (opts.html) node.innerHTML = opts.html;
    return node;
  }

  function emptyNote(text) {
    return el("p", { className: "empty-note", text });
  }

  function renderResults(data) {
    document.getElementById("overview-doctype").textContent =
      data.document_type || "Document";
    document.getElementById("overview-parties").textContent =
      data.parties && data.parties.length
        ? data.parties.join(", ")
        : "This could not be determined from the provided document.";
    document.getElementById("overview-duration").textContent =
      data.duration ||
      "This could not be determined from the provided document.";
    document.getElementById("overview-purpose").textContent =
      data.purpose ||
      "This could not be determined from the provided document.";

    const kt = document.getElementById("key-takeaways");
    kt.innerHTML = "";
    (data.key_takeaways || []).forEach((t) => {
      const item = el("div", { className: "kt-item", text: t });
      kt.appendChild(item);
    });
    if (!data.key_takeaways || !data.key_takeaways.length) {
      kt.hidden = true;
    } else {
      kt.hidden = false;
    }

    // Summary
    document.getElementById("summary-text").textContent =
      data.summary ||
      "This could not be determined from the provided document.";

    // Terms
    const termsList = document.getElementById("terms-list");
    termsList.innerHTML = "";
    if (data.important_terms && data.important_terms.length) {
      data.important_terms.forEach((term) => {
        const card = el("div", { className: "term-card" });
        card.appendChild(el("h4", { text: term.term || "Term" }));
        const rows = [
          ["What it says", term.whatItSays || term.what_it_says],
          ["In plain terms", term.simpleMeaning || term.simple_meaning],
          ["Why it matters", term.whyItMatters || term.why_it_matters],
        ];
        rows.forEach(([label, value]) => {
          if (!value) return;
          const row = el("div", { className: "term-row" });
          row.appendChild(el("span", { className: "term-label", text: label }));
          row.appendChild(el("span", { className: "term-value", text: value }));
          card.appendChild(row);
        });
        termsList.appendChild(card);
      });
    } else {
      termsList.appendChild(
        emptyNote("No key terms were identified in this document."),
      );
    }

    // Timeline
    const timelineList = document.getElementById("timeline-list");
    timelineList.innerHTML = "";
    if (data.timeline && data.timeline.length) {
      data.timeline.forEach((item) => {
        const li = el("li");
        li.appendChild(
          el("span", {
            className: "timeline-date",
            text: item.date_or_deadline || "Date not specified",
          }),
        );
        li.appendChild(
          el("p", { className: "timeline-action", text: item.action || "" }),
        );
        if (item.responsible_party) {
          li.appendChild(
            el("p", {
              className: "timeline-meta",
              text: `Responsible: ${item.responsible_party}`,
            }),
          );
        }
        if (item.consequence) {
          li.appendChild(
            el("span", {
              className: "timeline-consequence",
              text: item.consequence,
            }),
          );
        }
        timelineList.appendChild(li);
      });
    } else {
      timelineList.appendChild(
        emptyNote(
          "No specific deadlines or dates were identified in this document.",
        ),
      );
    }

    // Responsibilities
    const respUser = document.getElementById("resp-user");
    const respOther = document.getElementById("resp-other");
    respUser.innerHTML = "";
    respOther.innerHTML = "";
    (data.user_responsibilities || []).forEach((r) =>
      respUser.appendChild(el("li", { text: r })),
    );
    (data.other_party_responsibilities || []).forEach((r) =>
      respOther.appendChild(el("li", { text: r })),
    );
    if (!data.user_responsibilities || !data.user_responsibilities.length) {
      respUser.appendChild(
        emptyNote("This could not be determined from the provided document."),
      );
    }
    if (
      !data.other_party_responsibilities ||
      !data.other_party_responsibilities.length
    ) {
      respOther.appendChild(
        emptyNote("This could not be determined from the provided document."),
      );
    }

    // Risks
    const risksList = document.getElementById("risks-list");
    risksList.innerHTML = "";
    if (data.risks && data.risks.length) {
      const order = { HIGH: 0, MEDIUM: 1, LOW: 2 };
      const sorted = [...data.risks].sort(
        (a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3),
      );
      sorted.forEach((risk) => {
        const sev = risk.severity || "LOW";
        const card = el("div", { className: `risk-card ${sev}` });
        const head = el("div", { className: "risk-head" });
        head.appendChild(el("h4", { text: risk.issue || "Risk" }));
        head.appendChild(
          el("span", { className: `severity-badge ${sev}`, text: sev }),
        );
        card.appendChild(head);
        card.appendChild(el("p", { text: risk.explanation || "" }));
        risksList.appendChild(card);
      });
    } else {
      risksList.appendChild(
        emptyNote("No significant risks or red flags were identified."),
      );
    }

    // Clauses
    const clausesList = document.getElementById("clauses-list");
    clausesList.innerHTML = "";
    if (data.important_clauses && data.important_clauses.length) {
      data.important_clauses.forEach((c) => {
        const card = el("div", { className: "clause-card" });
        card.appendChild(el("h4", { text: c.title || "Clause" }));
        card.appendChild(el("p", { text: c.explanation || "" }));
        clausesList.appendChild(card);
      });
    } else {
      clausesList.appendChild(
        emptyNote("No standout clauses beyond what's covered elsewhere."),
      );
    }

    // Actions
    const actionsList = document.getElementById("actions-list");
    actionsList.innerHTML = "";
    if (data.recommended_actions && data.recommended_actions.length) {
      data.recommended_actions.forEach((a) =>
        actionsList.appendChild(el("li", { text: a })),
      );
    } else {
      actionsList.appendChild(emptyNote("No specific actions were flagged."));
    }

    // Lawyer questions
    const lawyerList = document.getElementById("lawyer-list");
    lawyerList.innerHTML = "";
    if (data.lawyer_questions && data.lawyer_questions.length) {
      data.lawyer_questions.forEach((q) =>
        lawyerList.appendChild(el("li", { text: q })),
      );
    } else {
      lawyerList.appendChild(
        emptyNote(
          "No specific questions were flagged — this document did not appear to raise ambiguous or high-risk issues.",
        ),
      );
    }

    // Disclaimer
    document.getElementById("disclaimer").textContent =
      data.disclaimer ||
      "This tool helps you understand a document in plain English. It is not a lawyer and does not provide legal advice.";

    // Reset to first tab
    activateTab("summary");
  }

  // ---------- Tabs ----------
  function activateTab(tabName) {
    document.querySelectorAll(".tab").forEach((t) => {
      const active = t.dataset.tab === tabName;
      t.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.hidden = p.dataset.panel !== tabName;
    });
  }

  document.getElementById("tabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (!btn) return;
    activateTab(btn.dataset.tab);
  });

  // ---------- Dropzone wiring ----------
  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) handleFile(fileInput.files[0]);
  });
  ["dragenter", "dragover"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  });

  function resetToUpload() {
    fileInput.value = "";
    clearUploadError();
    showScreen("upload");
  }

  startOverBtn.addEventListener("click", resetToUpload);
  oocRetryBtn.addEventListener("click", resetToUpload);
  errorRetryBtn.addEventListener("click", resetToUpload);

  showScreen("upload");
})();
