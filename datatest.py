import sqlite3
import pandas as pd

# Use the same DB_FILE path as in your app
DB_FILE = "[path to your database]"

# Connect and query
conn = sqlite3.connect(DB_FILE)
data = pd.read_sql_query("SELECT * FROM calorie_data", conn)
conn.close()

# Display data
print(data.head())
print(f"Total records: {len(data)}")

# Basic statistics
if len(data) > 0:
    print(f"Date range: {data['Date'].min()} to {data['Date'].max()}")
    print(f"Average calories: {data['TotalCalories'].mean():.1f}")
    print(f"Weight range: {data['Weight'].min()} to {data['Weight'].max()}")