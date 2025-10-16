import importlib
import subprocess
import sys

# -----------------------------
# Auto-install missing packages
# -----------------------------
required_packages = ["streamlit", "pandas", "matplotlib"]
for pkg in required_packages:
    if importlib.util.find_spec(pkg) is None:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


import streamlit as st
import json
import pandas as pd
import matplotlib.pyplot as plt
import re

# -----------------------------
# Universal Evaporation Function
# -----------------------------
def calculate_evaporation_auto(recipe_json, k=0.02, fraction=0.40, minutes_per_liter=7.5):
    """
    Calculates water evaporation using only:
    - cooking temperature (°C)
    - cooking time (minutes)
    - added water quantity (ml)
    Automatically estimates time-to-boil (t_heat).
    """

    # Extract method safely
    method_data = recipe_json.get("cooking_method", ["Boiling"])
    method = method_data[0] if isinstance(method_data, list) else method_data
    method = str(method).strip()

    method_factors = {
        "Boiling": 1.0,
        "Steaming": 0.5,
        "Pressure Cooking": 0.3,
        "Slow Cooking": 0.8
    }
    m = method_factors.get(method, 1.0)

    # Extract temperature (°C)
    temp_str = recipe_json.get("cooking_temperature", "100 °C")
    try:
        temp_C = float(temp_str.replace("°C", "").replace("°", "").strip())
    except:
        temp_C = 100.0

    # Extract total cooking time (minutes)
    time_str = recipe_json.get("cooking_time", "10 minutes")
    nums = re.findall(r'\d+', str(time_str))
    t_total = float(nums[0]) if nums else 10.0

    # Extract added water only
    added_water_ml = 0.0
    for ing in recipe_json.get("ingredients", []):
        name = str(ing.get("name", "")).lower()
        if "water" in name:
            try:
                q = float(ing.get("quantity", 0))
            except:
                q = 0.0
            unit = str(ing.get("unit", "")).lower()
            if unit.startswith("l"):
                q_ml = q * 1000.0
            else:
                q_ml = q
            added_water_ml += q_ml

    # Estimate heating time (t_heat)
    fraction_rule = fraction * t_total
    volume_rule = minutes_per_liter * (added_water_ml / 1000.0)
    estimated_t_heat = max(fraction_rule, volume_rule)
    t_heat = min(t_total, max(1.0, round(estimated_t_heat, 1)))
    t_evap = max(0.0, t_total - t_heat)

    # Temperature factor (ensures base at 100°C)
    fT = 1.0 + max(0.0, temp_C - 100.0)

    # Calculate evaporation percentage and ml
    percent_evap = min(100.0, k * m * fT * t_evap)
    evaporated_ml = added_water_ml * (percent_evap / 100.0)
    remaining_ml = max(0.0, added_water_ml - evaporated_ml)

    return {
        "method": method,
        "temp_C": temp_C,
        "t_total": t_total,
        "t_heat": t_heat,
        "t_evap": t_evap,
        "added_water_ml": added_water_ml,
        "evap_percent": percent_evap,
        "evap_ml": evaporated_ml,
        "remaining_ml": remaining_ml,
        "k": k,
        "method_factor": m
    }

# -----------------------------
# Streamlit UI
# -----------------------------
st.title("Water Evaporation Calculator")
st.markdown("""
Estimate **water loss due to evaporation** based only on:
- Cooking Method  
- Cooking Temperature  
- Cooking Time  
- Added Water Quantity  

This model automatically estimates how long it takes to reach boiling (t_heat),
then calculates evaporation during the remaining time.
""")

# JSON input
json_input = st.text_area("📥 Paste Recipe JSON Here", height=400)

# -----------------------------
# Button and Processing
# -----------------------------
if st.button("Calculate Water Loss"):
    try:
        data = json.loads(json_input)

        results = calculate_evaporation_auto(data)

        st.success("✅ Calculation Completed Successfully!")
        st.subheader("📊 Water Evaporation Results")

        st.write(f"**Cooking Method:** {results['method']}")
        st.write(f"**Cooking Temperature:** {results['temp_C']} °C")
        st.write(f"**Total Cooking Time:** {results['t_total']} min")
        st.write(f"**Estimated Heating Time (t_heat):** {results['t_heat']} min")
        st.write(f"**Evaporation Phase (t_evap):** {results['t_evap']} min")
        st.write(f"**Initial Water:** {results['added_water_ml']} ml")
        st.write(f"**Evaporated Water:** {results['evap_ml']:.2f} ml ({results['evap_percent']:.2f}%)")
        st.write(f"**Remaining Water:** {results['remaining_ml']:.2f} ml")

        # -----------------------------
        # Graphical Representation
        # -----------------------------
        st.subheader("📈 Water Evaporation Over Time")

        times = list(range(0, int(results["t_total"]) + 1))
        evap_list = []

        for t in times:
            temp_recipe = data.copy()
            temp_recipe["cooking_time"] = f"{t} minutes"
            r = calculate_evaporation_auto(temp_recipe)
            evap_list.append(r["evap_ml"])

        df = pd.DataFrame({"Cooking Time (min)": times, "Evaporated Water (ml)": evap_list})

        plt.figure(figsize=(8, 4))
        plt.plot(df["Cooking Time (min)"], df["Evaporated Water (ml)"], color="blue", marker='o')
        plt.axvline(results["t_heat"], color='red', linestyle='--', label=f"t_heat = {results['t_heat']} min")
        plt.title(f"Water Evaporation vs Time ({results['method']})")
        plt.xlabel("Cooking Time (min)")
        plt.ylabel("Evaporated Water (ml)")
        plt.legend()
        plt.grid(True)
        st.pyplot(plt)

    except Exception as e:
        st.error(f"⚠️ Error parsing JSON or calculating evaporation: {e}")

# -----------------------------
# Example JSON
# -----------------------------
st.markdown("""
---
### 🧩 Example JSON
```json
{
  "dish_name": "Boil Egg",
  "cooking_method": ["Boiling"],
  "cooking_time": "10 minutes",
  "cooking_temperature": "100 °C",
  "ingredients": [
    {"name": "Egg hen", "quantity": 40, "unit": "g"},
    {"name": "Water", "quantity": 500, "unit": "ml"}
  ]
}
```
""")

