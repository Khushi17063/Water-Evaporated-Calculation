import streamlit as st
import json
import re

# ------------------------
# Constants (Physics)
# ------------------------
SPECIFIC_HEAT_WATER = 4186.0        # J/(kg·K)
LATENT_HEAT_WATER   = 2_257_000.0   # J/kg
INITIAL_TEMP_C      = 25.0          # °C
GENERIC_POWER_W     = 1500.0        # W  (fixed internal)
GENERIC_EFFICIENCY  = 0.45          # —   (fixed internal, 0–1)

# ------------------------
# Constants (Empirical)
# ------------------------
ALLOWED_COOKING_METHODS = ["Boiling", "Steaming", "Pressure Cooking", "Slow Cooking"]

# Empirical evaporation fractions (per base time)
EVAPORATION_BASE = {
    "Boiling":          {"fraction": 0.10, "base_time": 10},  # 10% per 10 min
    "Steaming":         {"fraction": 0.05, "base_time": 10},  # 5% per 10 min
    "Pressure Cooking": {"fraction": 0.01, "base_time": 10},  # 1% per 10 min
    "Slow Cooking":     {"fraction": 0.08, "base_time": 60},  # 8% per 60 min
}

# Phase-change (boiling) temperature target per method for physics cap
PHASE_TEMP_BY_METHOD = {
    "Boiling":          100.0,
    "Steaming":         100.0,
    "Pressure Cooking": 105.0,   # adjust to 110.0 if desired
    "Slow Cooking":     100.0,   # physics evap only if reaches ~100°C
}

# ------------------------
# Helpers
# ------------------------
def _parse_minutes(s: str) -> int:
    """
    Extract minutes from inputs like:
      '10 min', '35 minutes', '18', '1h 20m', '1 h 5 m'
    Fallback: first integer if no h/m pattern is present.
    """
    if not s:
        return 0
    text = str(s).lower()
    # handle h/m patterns
    h = re.search(r"(\d+)\s*h", text)
    m = re.search(r"(\d+)\s*m", text)
    if h or m:
        hours = int(h.group(1)) if h else 0
        mins  = int(m.group(1)) if m else 0
        return hours * 60 + mins
    # fallback: first integer
    first = re.search(r"(\d+)", text)
    return int(first.group(1)) if first else 0

def _parse_temperature(val):
    """
    Accepts numbers (e.g., 100) or strings like '105 C', '94C', '90'
    Returns float (°C) or None if cannot parse.
    """
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        pass
    m = re.search(r"(-?\d+(\.\d+)?)", str(val))
    return float(m.group(1)) if m else None

def _contains_water(name: str) -> bool:
    """
    Looser matcher for direct water entries only.
    Includes: 'Water', 'Water (for steaming)', 'Water for dough', etc.
    Excludes stock/broth because they don't contain the word 'water'.
    """
    return "water" in (name or "").strip().lower()

def _water_ml_from_item(item) -> float:
    """
    Convert a single ingredient item to ml if it is water.
    Assumes:
      - 'ml' -> ml
      - 'g'  -> ml (for water 1 g ≈ 1 ml)
      - 'cup' -> 240 ml
      - 'tbsp'/'tablespoon' -> 15 ml
      - 'tsp'/'teaspoon' -> 5 ml
      Unknown units -> ignored.
    """
    try:
        qty  = float(item.get("quantity", 0))
    except Exception:
        return 0.0
    unit = str(item.get("unit", "")).strip().lower()

    if unit in ("", "ml", "g"):
        return qty
    if unit == "cup":
        return qty * 240.0
    if unit in ("tbsp", "tablespoon"):
        return qty * 15.0
    if unit in ("tsp", "teaspoon"):
        return qty * 5.0
    # extend here for more units if needed
    return 0.0

def _temp_factor(T_c, phase_temp: float) -> float:
    """
    Smooth temperature scaling for sub-boiling evaporation.
    0 at 70°C → 1 at phase temperature.
    Exponent 1.5 ramps faster near boiling (tunable).
    """
    if T_c is None:
        return 0.0
    t = (T_c - 70.0) / max(1e-9, (phase_temp - 70.0))
    t = max(0.0, min(1.0, t))
    return t ** 1.5

# ------------------------
# Hybrid Evaporation (JSON-driven temperature, fixed power/efficiency)
# ------------------------
def calculate_evaporated_water_hybrid(
    water_ml: float,
    cooking_method: str,
    cooking_time_min: int,
    cooking_temperature_c,  # float | None
    power_W: float = GENERIC_POWER_W,
    efficiency: float = GENERIC_EFFICIENCY,
    T_initial_C: float = INITIAL_TEMP_C,
) -> float:
    """
    Hybrid evaporation estimate:
      - Physics cap via energy balance:
          • Evaporation allowed ONLY if JSON 'cooking_temperature' >= method phase temp.
          • Sensible heating computed up to the method's phase temp.
      - Empirical limit via method fraction scaling, further scaled by a temperature factor below phase temp.
      - Final:
          • If temp >= phase temp: min(available, physics cap, empirical_scaled)
          • If temp <  phase temp: min(available, empirical_scaled)   (ignore physics=0 clamp)
    Returns evaporated mass in grams (1 mL ≈ 1 g).
    """
    base = EVAPORATION_BASE.get(cooking_method)
    phase_temp = PHASE_TEMP_BY_METHOD.get(cooking_method)
    if (not base) or (phase_temp is None) or (water_ml <= 0) or (cooking_time_min <= 0) or (power_W <= 0) or (efficiency <= 0):
        return 0.0

    water_g  = float(water_ml)           # 1 mL ≈ 1 g
    water_kg = water_g / 1000.0
    t_s      = cooking_time_min * 60.0

    # -------- Physics cap --------
    E_in_J = power_W * t_s * efficiency
    at_or_above_phase = (cooking_temperature_c is not None) and (cooking_temperature_c >= phase_temp - 1e-9)

    if not at_or_above_phase:
        m_phys_evap_g = 0.0
    else:
        deltaT_C     = max(0.0, phase_temp - T_initial_C)
        Q_sensible_J = water_kg * SPECIFIC_HEAT_WATER * deltaT_C
        if E_in_J <= Q_sensible_J:
            m_phys_evap_g = 0.0
        else:
            E_evap_J      = E_in_J - Q_sensible_J
            m_evap_kg     = E_evap_J / LATENT_HEAT_WATER
            m_phys_evap_g = max(0.0, m_evap_kg * 1000.0)

    # -------- Empirical limit (temperature-scaled) --------
    tf = _temp_factor(cooking_temperature_c, phase_temp)
    evap_fraction = base["fraction"] * (cooking_time_min / base["base_time"]) * tf
    evap_fraction = max(0.0, min(1.0, evap_fraction))  # clamp 0..1
    m_emp_evap_g  = water_g * evap_fraction

    # -------- Final merge --------
    if at_or_above_phase:
        m_final_g = min(water_g, m_phys_evap_g, m_emp_evap_g)
    else:
        m_final_g = min(water_g, m_emp_evap_g)

    return max(0.0, float(m_final_g))

# ------------------------
# Streamlit UI
# ------------------------
st.set_page_config(page_title="Cooking Water Evaporation (Hybrid Model)", layout="centered")
st.title("Water Evaporation Calculator")

st.markdown("""
Paste your dish JSON below.

**Notes**
- Allowed `cooking_style`: Boiling, Steaming, Pressure Cooking, Slow Cooking  
- `cooking_temperature` is read **from JSON** (e.g., `"100 C"` or `105`).  
- Only **direct water** entries are counted (ingredients whose name contains `"water"`).  
- **Model:** Below the method's phase temperature we scale the empirical rate by temperature; at/above phase we also apply an energy-based physics cap.  
""")

json_input = st.text_area(
    "Paste JSON here:",
    height=340,
    placeholder=(
        '{"dish_name":"Boiled Rice","cooking_style":"Boiling","cooking_time":"12 min",'
        '"cooking_temperature":"100 C","ingredients":[{"name":"Water","quantity":500,"unit":"ml"}]}'
    ),
)

if st.button("Calculate Evaporation"):
    try:
        dish_data = json.loads(json_input)

        cooking_method = dish_data.get("cooking_style")
        cooking_time_str = dish_data.get("cooking_time")
        cooking_time_min = _parse_minutes(cooking_time_str)
        cooking_temp_c   = _parse_temperature(dish_data.get("cooking_temperature"))

        if cooking_method not in ALLOWED_COOKING_METHODS:
            st.error(f"Cooking method '{cooking_method}' is not allowed. Use one of {ALLOWED_COOKING_METHODS}.")
        elif cooking_time_min <= 0:
            st.error(f"Could not parse a positive cooking time from: {cooking_time_str!r}")
        elif cooking_temp_c is None:
            st.error("Could not parse 'cooking_temperature' from JSON (e.g., '100 C').")
        else:
            # Sum all direct water entries
            water_ml = 0.0
            ingredients = dish_data.get("ingredients", [])
            for item in ingredients:
                if _contains_water(item.get("name", "")):
                    water_ml += _water_ml_from_item(item)

            if water_ml <= 0:
                st.warning("No direct water found in the ingredients (or total quantity ≤ 0). Evaporation = 0 ml")
            else:
                evap_ml = calculate_evaporated_water_hybrid(
                    water_ml=water_ml,
                    cooking_method=cooking_method,
                    cooking_time_min=cooking_time_min,
                    cooking_temperature_c=cooking_temp_c,
                    power_W=GENERIC_POWER_W,           # fixed internal
                    efficiency=GENERIC_EFFICIENCY,     # fixed internal
                    T_initial_C=INITIAL_TEMP_C,
                )
                st.success(f"Water Evaporated: {evap_ml:.2f} ml")
                with st.expander("Details"):
                    st.write({
                        "dish_name": dish_data.get("dish_name"),
                        "inputs": {
                            "cooking_method": cooking_method,
                            "cooking_time_min": cooking_time_min,
                            "cooking_temperature_c": cooking_temp_c,
                            "direct_water_total_ml": water_ml,
                        },
                        "physics": {
                            "power_W": GENERIC_POWER_W,
                            "efficiency": GENERIC_EFFICIENCY,
                            "T_initial_C": INITIAL_TEMP_C,
                            "phase_temp_for_method": PHASE_TEMP_BY_METHOD.get(cooking_method),
                        },
                        "empirical_base": EVAPORATION_BASE.get(cooking_method, {}),
                        "notes": "Sub-boiling: temp-scaled empirical; At/above phase: min(available, physics, empirical). 1 mL ≈ 1 g.",
                    })

    except Exception as e:
        st.error(f"Invalid JSON or data format: {e}")
