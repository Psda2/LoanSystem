document
  .getElementById("evaluation-form")
  .addEventListener("submit", async (e) => {
    e.preventDefault();

    const resultDisplay = document.getElementById("result-display");
    resultDisplay.innerHTML = '<div class="loader">Analyzing...</div>';

    const data = {
      isSriLankan: document.getElementById("is-srilankan").checked,
      loanType: document.getElementById("loan-type").value,
      age: document.getElementById("age").value,
      income: document.getElementById("income").value,
      dti: document.getElementById("dti").value,
      cribScore: document.getElementById("crib-score").value,
      hasPreviousArrears: document.getElementById("has-arrears").checked,
    };

    try {
      const response = await fetch("/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });

      const result = await response.json();

      const diagnosisClass =
        result.diagnosis === "Approved" ? "badge-approved" : "badge-rejected";

      let detailsHtml = "";
      result.details.forEach((detail) => {
        detailsHtml += `<li>${detail}</li>`;
      });

      resultDisplay.innerHTML = `
            <div class="diagnosis-result">
                <span class="badge ${diagnosisClass}">${result.diagnosis}</span>
                <span class="category-name">${result.category}</span>
                <ul class="details-list">
                    ${detailsHtml}
                </ul>
            </div>
        `;
    } catch (error) {
      resultDisplay.innerHTML = `<div class="error">Connection Error: ${error.message}</div>`;
    }
  });
