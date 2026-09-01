let currentThreadId = localStorage.getItem("travel_thread_id") || null;
let latestAnswerMarkdown = "";
let waitingForApproval = false;

const AGENT_LABELS = {
  flight_agent: "✈️ Flight Agent",
  hotel_agent: "🏨 Hotel Agent",
  weather_agent: "🌦️ Weather Agent",
  budget_agent: "💰 Budget Agent",
  itinerary_agent: "🗓️ Itinerary Agent"
};

function setPrompt(text) {
  document.getElementById("userInput").value = text;
}

function setLoading(isLoading, mode = "draft") {
  if (mode === "approval") {
    const approveBtn = document.getElementById("approveBtn");
    const reviseBtn = document.getElementById("reviseBtn");

    if (approveBtn) approveBtn.disabled = isLoading;
    if (reviseBtn) reviseBtn.disabled = isLoading;

    return;
  }

  const sendBtn = document.getElementById("sendBtn");
  const btnText = document.getElementById("btnText");
  const btnLoader = document.getElementById("btnLoader");

  if (sendBtn) sendBtn.disabled = isLoading;

  if (btnText && btnLoader) {
    btnText.classList.toggle("hidden", isLoading);
    btnLoader.classList.toggle("hidden", !isLoading);
  }
}

function buildResultSectionNavigation() {
  const resultContent = document.getElementById("resultPageContent");
  const nav = document.getElementById("resultSectionNav");

  if (!resultContent || !nav) {
    return;
  }

  nav.innerHTML = "";

  // Find all section headings in the generated itinerary.
  // h2 is usually ideal for major sections.
  const headings = resultContent.querySelectorAll("h1,h2,h3");

  headings.forEach((heading, index) => {
    // Create a stable ID for the heading
    let id = heading.id;

    if (!id) {
      id = `itinerary-section-${index}`;
      heading.id = id;
    }

    const button = document.createElement("button");

    button.type = "button";
    button.className = "result-section-link";
    button.textContent = heading.textContent.trim();

    button.addEventListener("click", () => {
      const target = document.getElementById(id);

      if (target) {
        target.scrollIntoView({
          behavior: "smooth",
          block: "start"
        });

        // Update URL hash without jumping
        history.replaceState(null, "", `#${id}`);
      }
    });

    nav.appendChild(button);
  });
}


function showError(message) {
  const errorBox = document.getElementById("errorBox");
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
  errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
}

function hideError() {
  const errorBox = document.getElementById("errorBox");
  errorBox.classList.add("hidden");
  errorBox.textContent = "";
}

function renderMarkdown(element, markdown) {
  if (typeof marked !== "undefined") {
    element.innerHTML = marked.parse(markdown || "");
  } else {
    element.innerText = markdown || "";
  }

  buildResultSectionNavigation();

}

function showWorkflow(data) {
  const section = document.getElementById("workflowSection");
  const reasoning = document.getElementById("supervisorReasoning");
  const chips = document.getElementById("agentChips");
  const guardrailBadge = document.getElementById("guardrailBadge");

  reasoning.textContent = data.supervisor_reasoning || "Supervisor routing completed.";
  chips.innerHTML = "";

  (data.selected_agents || []).forEach((agent) => {
    const chip = document.createElement("span");
    chip.className = "agent-chip";
    chip.textContent = AGENT_LABELS[agent] || agent;
    chips.appendChild(chip);
  });

  if (data.guardrail_allowed === false) {
    guardrailBadge.textContent = "Guardrail blocked";
    guardrailBadge.classList.add("blocked");
  } else {
    guardrailBadge.textContent = "Guardrail passed";
    guardrailBadge.classList.remove("blocked");
  }

  section.classList.remove("hidden");
}

function persistResultState(answer, threadId, isDraft = false, requiresApproval = false, approvalRequest = "", tripConstraints = {}) {
  latestAnswerMarkdown = answer || "";
  localStorage.setItem("travel_result_markdown", latestAnswerMarkdown);
  localStorage.setItem("travel_result_thread_id", threadId || "");
  localStorage.setItem("travel_result_title", isDraft ? "Draft Travel Plan" : "Your Final AI Travel Plan");
  localStorage.setItem("travel_requires_approval", requiresApproval.toString());
  localStorage.setItem("travel_approval_request", approvalRequest);
  localStorage.setItem("travel_trip_constraints", JSON.stringify(tripConstraints));
}

async function sendMessage() {
  hideError();

  if (waitingForApproval) {
    showError(
      "Please approve or revise the current draft before starting another plan."
    );
    return;
  }

  const input = document.getElementById("userInput");

  if (!input) {
    showError("Input field not found.");
    return;
  }

  const message = input.value.trim();

  if (!message) {
    showError("Please enter your travel request first.");
    return;
  }

  setLoading(true, "draft");

  try {
    const response = await fetch("/api/travel", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        message: message,
        thread_id: currentThreadId
      })
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || "Something went wrong.");
    }

    // Save thread ID
    currentThreadId = data.thread_id;

    localStorage.setItem(
      "travel_thread_id",
      currentThreadId
    );

    // Build trip constraints
    const tripConstraints = {
      destination: data.destination || "",
      origin: data.origin || "",
      duration: data.duration || "",
      budget: data.budget_results || "",
      travel_style: data.travel_style || ""
    };

    // Get the actual itinerary
    const answer = data.itinerary || data.answer || "";

    // Save everything before navigating to /result
    persistResultState(
      answer,
      data.thread_id,
      data.requires_approval || false,
      data.requires_approval || false,
      data.approval_request || "",
      tripConstraints
    );

    // Go to result page
    window.location.href = "/result";

  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false, "draft");
  }
}

function renderResultPageItinerary(
  answer,
  threadId,
  isDraft = false,
  requiresApproval = false,
  approvalRequest = "",
  tripConstraints = {}
) {

  if (window.location.pathname !== "/result") {
    window.location.href = "/result";
  return;
}


  // Persist the new version so refresh still shows it
  persistResultState(
    answer,
    threadId,
    isDraft,
    requiresApproval,
    approvalRequest,
    tripConstraints
  );

  const resultContent =
    document.getElementById("resultPageContent");

  const resultTitle =
    document.getElementById("resultPageTitle");

  const approvalSection =
    document.getElementById("approvalSectionResult");

  const approvalRequestElement =
    document.getElementById("approvalRequestResult");

  // Render the NEW itinerary directly into the result page
  if (resultContent) {
    renderMarkdown(resultContent, answer || "");
  }

  // Update title
  if (resultTitle) {
    resultTitle.textContent = isDraft
      ? "Draft Travel Plan"
      : "Your Final AI Travel Plan";
  }

  // Update approval UI
  if (approvalSection) {
    if (requiresApproval) {
      approvalSection.classList.remove("hidden");

      if (approvalRequestElement) {
        approvalRequestElement.textContent =
          approvalRequest ||
          "Please review the revised plan.";
      }
    } else {
      approvalSection.classList.add("hidden");
    }
  }

  latestAnswerMarkdown = answer || "";
  currentThreadId = threadId;
}


function hideApproval() {
  waitingForApproval = false;
  document.getElementById("approvalSection").classList.add("hidden");
  document.getElementById("approvalFeedback").value = "";
}




async function submitApproval(approved) {
  hideError();

  if (!currentThreadId || !waitingForApproval) {
    showError("There is no draft waiting for approval.");
    return;
  }

  const feedbackInput = document.getElementById("approvalFeedback");
  const feedback = feedbackInput.value.trim();

  if (!approved && !feedback) {
    showError("Please enter revision feedback before requesting changes.");
    feedbackInput.focus();
    return;
  }

  setLoading(true, "approval");

  try {
    const response = await fetch("/api/travel/approve", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        thread_id: currentThreadId,
        approved: approved,
        feedback: feedback
      })
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || "Could not resume the travel workflow.");
    }

    showWorkflow(data);

    if (data.requires_approval) {
      const tripConstraints = {
        destination: data.destination || "",
        origin: data.origin || "",
        duration: data.duration || "",
        budget: data.budget_results || "",
        travel_style: data.travel_style || ""
      };

      renderResultPageItinerary(
        data.itinerary || data.answer,
        data.thread_id,
        data.requires_approval,
        data.requires_approval,
        data.approval_request || "",
        tripConstraints
      );

    } else {
      const tripConstraints = {
        destination: data.destination || "",
        origin: data.origin || "",
        duration: data.duration || "",
        budget: data.budget_results || "",
        travel_style: data.travel_style || ""
      };
      hideApproval();

      renderResultPageItinerary(
        data.itinerary || data.answer,
        data.thread_id,
        data.requires_approval,
        data.requires_approval,
        data.approval_request || "",
        tripConstraints
      );
    }
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false, "approval");
  }
}

async function submitApprovalFromResult(approved) {
  hideError();

  if (!currentThreadId) {
    showError("No active travel plan to approve.");
    return;
  }

  const feedbackInput = document.getElementById("approvalFeedbackResult");
  
  const feedback = feedbackInput ? feedbackInput.value.trim() : "";
  console.log('Feedback for revise: ',feedback)

  if (!approved && !feedback) {
    showError("Please enter revision feedback before requesting changes.");
    if (feedbackInput) feedbackInput.focus();
    return;
  }

  setLoading(true, "approval");

  try {
    const response = await fetch("/api/travel/approve", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        thread_id: currentThreadId,
        approved: approved,
        feedback: feedback
      })
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || "Could not resume the travel workflow.");
    }

    showWorkflow(data);

    if (data.requires_approval) {
      const tripConstraints = {
        destination: data.destination || "",
        origin: data.origin || "",
        duration: data.duration || "",
        budget: data.budget_results || "",
        travel_style: data.travel_style || ""
      };

      console.log("New itinerary:", data.itinerary);
      console.log("New answer:", data.answer);

      renderResultPageItinerary(
        data.itinerary || data.answer,
        data.thread_id,
        data.requires_approval,
        data.requires_approval,
        data.approval_request || "",
        tripConstraints
      );


      
      // Show approval section on result page
      const approvalSection = document.getElementById("approvalSectionResult");
      const approvalRequest = document.getElementById("approvalRequestResult");
      if (approvalSection && approvalRequest) {
        approvalRequest.textContent = data.approval_request || "Please review the revised plan.";
        approvalSection.classList.remove("hidden");
      }

      // Clear feedback input for next iteration
      if (feedbackInput) feedbackInput.value = "";
    } else {
      const tripConstraints = {
        destination: data.destination || "",
        origin: data.origin || "",
        duration: data.duration || "",
        budget: data.budget_results || "",
        travel_style: data.travel_style || ""
      };

      renderResultPageItinerary(
        data.itinerary || data.answer,
        data.thread_id,
        data.requires_approval,
        data.requires_approval,
        data.approval_request || "",
        tripConstraints
      );
      
      // Hide approval section when approved
      const approvalSection = document.getElementById("approvalSectionResult");
      if (approvalSection) approvalSection.classList.add("hidden");
    }
  } catch (error) {
    showError(error.message);
  } finally {
    setLoading(false, "approval");
  }
}

function copyResult() {
  const resultBox = document.getElementById("resultBox") || document.getElementById("resultPageContent");
  const text = resultBox ? resultBox.innerText : (latestAnswerMarkdown || "");

  if (!text) {
    return;
  }

  navigator.clipboard.writeText(text)
    .then(() => {
      const copyBtn = document.querySelector(".copy-btn");
      if (!copyBtn) return;
      const oldText = copyBtn.textContent;
      copyBtn.textContent = "Copied!";

      setTimeout(() => {
        copyBtn.textContent = oldText;
      }, 1400);
    })
    .catch(() => {
      showError("Could not copy result.");
    });
}

function downloadPDF() {
  const pdfContent = document.getElementById("pdfContent") || document.getElementById("resultPageContent");

  if (!latestAnswerMarkdown || !pdfContent) {
    showError("No travel plan available to download.");
    return;
  }

  const downloadBtn = document.querySelector(".download-btn");
  if (!downloadBtn) return;

  const oldText = downloadBtn.textContent;
  downloadBtn.textContent = "Preparing PDF...";
  downloadBtn.disabled = true;

  const options = {
    margin: 0.5,
    filename: "ai-travel-plan.pdf",
    image: {
      type: "jpeg",
      quality: 0.98
    },
    html2canvas: {
      scale: 2,
      useCORS: true,
      backgroundColor: "#ffffff"
    },
    jsPDF: {
      unit: "in",
      format: "a4",
      orientation: "portrait"
    },
    pagebreak: {
      mode: ["avoid-all", "css", "legacy"]
    }
  };

  html2pdf()
    .set(options)
    .from(pdfContent)
    .save()
    .then(() => {
      downloadBtn.textContent = oldText;
      downloadBtn.disabled = false;
    })
    .catch(() => {
      downloadBtn.textContent = oldText;
      downloadBtn.disabled = false;
      showError("Could not download PDF.");
    });
}

document.addEventListener("keydown", function(event) {
  if (event.ctrlKey && event.key === "Enter") {
    sendMessage();
  }
});