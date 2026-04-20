import pandas as pd
import os

# Create sample data matching the Google Form structure
data = {
    "Overall_Satisfaction": [8, 9, 7, 10, 6],
    "Content_Quality_Rating": ["Good", "Excellent", "Fair", "Good", "Excellent"],
    "Future_Topics": [
        "FinTech, Data Analytics",
        "ESG Investing, Alternative Investments",
        "Regulatory Compliance, Personal Finance",
        "FinTech, ESG, AI",
        "Crypto, Risk Management"
    ],
    "Networking_Rating": [4, 5, 3, 4, 5],
    "Attend_Next_Year": [
        "Probably Yes",
        "Definitely Yes",
        "Unsure",
        "Probably Yes",
        "Definitely No"
    ],
    "Email": [
        "user1@example.com",
        "user2@company.com",
        "user3@gmail.com",
        "user4@yahoo.com",
        "user5@outlook.com"
    ],
    "Feedback": [
        "Great event with excellent speakers",
        "Very informative sessions",
        "Well organized conference",
        "Looking forward to next year",
        "Good networking opportunities"
    ]
}

df = pd.DataFrame(data)

# Save as Excel
excel_path = "sample_form_data.xlsx"
df.to_excel(excel_path, index=False, sheet_name="Form Data")

# Also save as CSV
csv_path = "sample_form_data.csv"
df.to_csv(csv_path, index=False)

print("Created sample template files:")
print(f"   - {excel_path}")
print(f"   - {csv_path}")
print("\nSample data preview:")
print(df.head())
print(f"\nTotal rows: {len(df)}")
print(f"Columns: {list(df.columns)}")
