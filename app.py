import os
import re
import io
import json
import base64

import matplotlib
matplotlib.use('Agg')  # For servers without a display
import matplotlib.pyplot as plt

from flask import Flask, request, jsonify, render_template
from groq import Groq

app = Flask(__name__)

# Configure your Groq API key (or do it externally via environment variable)
os.environ['GROQ_API_KEY'] = 'your_api_key_here'
client = Groq(api_key=os.environ['GROQ_API_KEY'])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate_report', methods=['POST'])
def generate_report():
    data = request.get_json()
    salary = data.get('salary', 0)
    additional_income = data.get('additionalIncome', 0)
    investments = data.get('investments', 0)
    bonuses = data.get('bonuses', 0)
    gov_benefits = data.get('govBenefits', 0)
    expenses = data.get('expenses', [])

    total_income = salary + additional_income + investments + bonuses + gov_benefits

    # Build expense text for prompt
    expenses_list = []
    for e in expenses:
        e_type = e.get('type', 'Unknown')
        e_amt = float(e.get('amount', 0))
        e_cat = e.get('category', 'Uncategorized')
        expenses_list.append(f"{e_type} (${e_amt}, category: {e_cat})")
    expenses_str = "; ".join(expenses_list) if expenses_list else "No expenses listed."

    # Prompt for the textual budget
    prompt = (
        f"Given the following data:\n"
        f"- Salary: ${salary}\n"
        f"- Additional income: ${additional_income}\n"
        f"- Investments/passive: ${investments}\n"
        f"- Bonuses/commissions: ${bonuses}\n"
        f"- Government benefits: ${gov_benefits}\n"
        f"- Expenses: {expenses_str}\n"
        f"Total monthly income = ${total_income}.\n\n"
        f"Create a monthly budget report with a summary of major categories, leftover (net savings), and suggestions."
    )

    completion = client.chat.completions.create(
        model="deepseek-r1-distill-llama-70b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_completion_tokens=1024,
        top_p=0.95,
        stream=True,
        stop=None,
    )

    raw_report = ""
    for chunk in completion:
        raw_report += chunk.choices[0].delta.content or ""

    return jsonify({"report": raw_report})


@app.route('/generate_charts', methods=['POST'])
def generate_charts():
    """
    1) Ask the LLM for chain-of-thought in <think> plus JSON data:
       - categories_breakdown (dict)
       - monthly_investment_recommendation (number)
       - projected_balance_by_year (list of 10 floats)
       - explanation (optional short text)
    2) Parse out <think> and the JSON.
    3) If the LLM doesn't provide valid data, fallback to local calculations.
    4) Build:
       - Pie chart of categories as % of total monthly income
       - Line chart for a 10-year Roth IRA projection
    """
    data = request.get_json()

    age = data.get('age', 30)
    salary = data.get('salary', 0)
    additional_income = data.get('additionalIncome', 0)
    investments = data.get('investments', 0)
    bonuses = data.get('bonuses', 0)
    gov_benefits = data.get('govBenefits', 0)
    expenses = data.get('expenses', [])

    total_income = salary + additional_income + investments + bonuses + gov_benefits

    # Summarize user expenses for the prompt
    expenses_list_str = "; ".join(
        f"{e.get('type','?')} (${e.get('amount',0)}, {e.get('category','?')})"
        for e in expenses
    )

    # LLM prompt
    prompt = (
        f"You are analyzing a user's finances.\n"
        f"User's age: {age}.\n"
        f"Total monthly income: ${total_income}.\n"
        f"Expenses: {expenses_list_str}.\n\n"
        f"Reply with:\n"
        f"<think>Your chain-of-thought here.</think>\n"
        f"Then a valid JSON object with:\n"
        f"{{\n"
        f"  \"categories_breakdown\": {{ \"Housing\": <dollar>, \"Groceries\": <dollar>, ...}},\n"
        f"  \"monthly_investment_recommendation\": <number>,\n"
        f"  \"projected_balance_by_year\": [<10 floats>],\n"
        f"  \"explanation\": \"(short final text)\"\n"
        f"}}\n"
        f"No extra text beyond those elements.\n"
    )

    completion = client.chat.completions.create(
        model="deepseek-r1-distill-llama-70b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,  # more deterministic
        max_completion_tokens=1024,
        top_p=1.0,
        stream=True,
        stop=None,
    )

    full_response = ""
    for chunk in completion:
        full_response += chunk.choices[0].delta.content or ""

    # Extract any <think> content
    import re
    think_pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
    think_matches = think_pattern.findall(full_response)
    chain_of_thought = think_matches[0].strip() if think_matches else None

    # Remove <think> block, leaving just JSON
    stripped_text = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL).strip()

    # Parse JSON
    try:
        structured_data = json.loads(stripped_text)
    except json.JSONDecodeError:
        structured_data = {}

    categories_breakdown = structured_data.get("categories_breakdown", {})
    monthly_investment = structured_data.get("monthly_investment_recommendation", 0)
    balance_projection = structured_data.get("projected_balance_by_year", [])

    # --- Fallback logic if LLM's data is invalid or empty ---
    if not categories_breakdown or sum(categories_breakdown.values()) <= 0:
        # Build from user's actual input
        categories_breakdown = build_category_breakdown(expenses)

    if not balance_projection or len(balance_projection) < 2:
        # Fallback: do a naive 6% annual return, monthly compounding for 10 years
        leftover = total_income - sum(categories_breakdown.values())
        # If the LLM gave 0 recommendation, let's pick 20% leftover
        if monthly_investment <= 0 and leftover > 0:
            monthly_investment = leftover * 0.20
        balance_projection = calculate_projection(age, monthly_investment)

    # --- 1) Pie Chart (Expenses as % of total monthly income) ---
    labels = []
    values = []
    for cat, amt in categories_breakdown.items():
        labels.append(cat)
        values.append(float(amt))

    if not values or sum(values) <= 0:
        labels = ["No Data"]
        values = [1]

    fig1, ax1 = plt.subplots()
    ax1.pie(values, labels=labels, autopct='%1.1f%%')
    ax1.set_title('Expenses as % of Total Income')
    plt.tight_layout()

    buf1 = io.BytesIO()
    fig1.savefig(buf1, format='png')
    buf1.seek(0)
    chart1_base64 = base64.b64encode(buf1.read()).decode('utf-8')
    plt.close(fig1)

    # --- 2) Line Chart for 10-year projection ---
    fig2, ax2 = plt.subplots()
    if balance_projection and any(balance_projection):
        x_vals = list(range(len(balance_projection)))
        ax2.plot(x_vals, balance_projection, marker='o')
        ax2.set_xticks(x_vals)
        ax2.set_xticklabels([f"Year {i}" for i in x_vals])
        ax2.set_title('Projected Roth IRA Growth')
    else:
        ax2.text(0.5, 0.5, "No projection data", ha='center', va='center')
        ax2.set_title('Projected Roth IRA Growth')

    ax2.set_xlabel('Years from now')
    ax2.set_ylabel('Balance (USD)')
    plt.tight_layout()

    buf2 = io.BytesIO()
    fig2.savefig(buf2, format='png')
    buf2.seek(0)
    chart2_base64 = base64.b64encode(buf2.read()).decode('utf-8')
    plt.close(fig2)

    return jsonify({
        "chart1": chart1_base64,
        "chart2": chart2_base64,
        "think": chain_of_thought,
        "structuredData": structured_data
    })


def build_category_breakdown(expenses):
    """
    Summarize the user's expenses by category from input.
    Returns a dict {category: total_amount}.
    """
    cat_dict = {}
    for e in expenses:
        cat = e.get('category', 'Miscellaneous')
        amt = float(e.get('amount', 0))
        cat_dict[cat] = cat_dict.get(cat, 0) + amt
    return cat_dict


def calculate_projection(age, monthly_invest):
    """
    A simple 10-year projection with 6% annual growth, monthly compounding,
    starting from $0. Returns a list of 11 points (year 0..10).
    """
    annual_return = 0.06
    monthly_return = annual_return / 12
    months = 10 * 12
    balance = 0.0
    results = []

    for m in range(months + 1):
        # Every 12 months, record the year-based index
        if m % 12 == 0:
            results.append(round(balance, 2))
        # deposit + growth
        balance += monthly_invest
        balance *= (1 + monthly_return)

    return results

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
