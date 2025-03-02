function addExpenseRow() {
  const tableBody = document.querySelector('#expenseTable tbody');
  const newRow = document.createElement('tr');

  newRow.innerHTML = `
    <td><input type="text" name="expenseType" placeholder="e.g. Rent" required></td>
    <td><input type="number" name="expenseAmount" placeholder="Amount" required></td>
    <td>
      <select name="expenseCategory" required>
        <option value="Housing">Housing</option>
        <option value="Utilities">Utilities</option>
        <option value="Insurance">Insurance</option>
        <option value="Groceries">Groceries</option>
        <option value="Transportation">Transportation</option>
        <option value="Entertainment">Entertainment</option>
        <option value="Miscellaneous">Miscellaneous</option>
      </select>
    </td>
    <td>
      <button type="button" onclick="deleteExpenseRow(this)">Delete</button>
    </td>
  `;

  tableBody.appendChild(newRow);
}

function deleteExpenseRow(button) {
  const row = button.closest('tr');
  row.remove();
}

document.getElementById('expenseForm').addEventListener('submit', async function (event) {
  event.preventDefault();

  // Gather user inputs
  const age = parseInt(document.getElementById('age').value, 10) || 0;
  const salary = parseFloat(document.getElementById('salary').value) || 0;
  const additionalIncome = parseFloat(document.getElementById('additionalIncome').value) || 0;
  const investments = parseFloat(document.getElementById('investments').value) || 0;
  const bonuses = parseFloat(document.getElementById('bonuses').value) || 0;
  const govBenefits = parseFloat(document.getElementById('govBenefits').value) || 0;

  // Collect expenses
  const rows = document.querySelectorAll('#expenseTable tbody tr');
  const expensesData = [];
  rows.forEach(row => {
    const expenseType = row.querySelector('input[name="expenseType"]').value;
    const expenseAmount = parseFloat(row.querySelector('input[name="expenseAmount"]').value) || 0;
    const expenseCategory = row.querySelector('select[name="expenseCategory"]').value;

    expensesData.push({
      type: expenseType,
      amount: expenseAmount,
      category: expenseCategory
    });
  });

  // Build JSON
  const formData = {
    age,
    salary,
    additionalIncome,
    investments,
    bonuses,
    govBenefits,
    expenses: expensesData
  };

  // 1) Call /generate_report for the textual budget
  let llmReport;
  try {
    const resp = await fetch('/generate_report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData)
    });
    if (!resp.ok) throw new Error(`Report error: ${resp.statusText}`);

    const data = await resp.json();
    llmReport = data.report;

    // Display text-based report
    const reportContainer = document.getElementById('reportOutput');
    reportContainer.innerHTML = `
      <h3>Your Budget Report</h3>
      <pre>${llmReport}</pre>
    `;

  } catch (err) {
    console.error('Failed to get budget report:', err);
    alert('Error generating budget report.');
    return;
  }

  // 2) Call /generate_charts for the charts (pie + projection)
  try {
    const chartResp = await fetch('/generate_charts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData)
    });
    if (!chartResp.ok) throw new Error(`Chart error: ${chartResp.statusText}`);

    const chartData = await chartResp.json();

    // 2a) If there's a chain-of-thought in chartData.think, show it
    if (chartData.think) {
      const thinkDetails = document.getElementById('thinkDetails');
      const thinkContent = document.getElementById('thinkContent');
      thinkContent.textContent = chartData.think;  // preserve line breaks with .textContent
      thinkDetails.style.display = 'block';
    } else {
      // Hide chain-of-thought if none
      document.getElementById('thinkDetails').style.display = 'none';
    }

    // 2b) Insert Base64-encoded chart images
    document.getElementById('chart1Image').src = `data:image/png;base64,${chartData.chart1}`;
    document.getElementById('chart2Image').src = `data:image/png;base64,${chartData.chart2}`;

    // Show the charts
    document.getElementById('chartsContainer').style.display = 'block';

  } catch (err) {
    console.error('Failed to get charts:', err);
    alert('Error generating charts.');
  }
});
