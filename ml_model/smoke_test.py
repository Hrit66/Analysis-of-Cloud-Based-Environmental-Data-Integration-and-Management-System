import sys
sys.path.insert(0, ".")
from serving.inference import calculate_aqi, calculate_wqi

# Test AQI (CPCB formula)
r = calculate_aqi({"pm25": 55.0, "no2": 80.0, "pm10": 100.0})
print("AQI =", r["aqi"], " | Category =", r["category"], " | Dominant =", r["dominant_pollutant"])
print("Sub-indices =", r["sub_indices"])
assert r["aqi"] >= 0, "AQI must be non-negative"
assert r["category"] in ("Good","Satisfactory","Moderate","Poor","Very Poor","Severe"), "Invalid category"

# Test WQI (BIS formula)
w = calculate_wqi({"pH": 7.2, "turbidity": 2.5, "TDS": 320.0, "DO": 6.5, "nitrates": 15.0})
print("WQI =", w["wqi"], " | Category =", w["category"])
assert w["wqi"] >= 0, "WQI must be non-negative"

# Test CPCB breakpoint edge cases
r0 = calculate_aqi({"pm25": 0.0})
assert r0["aqi"] == 0, "PM2.5=0 should give AQI=0"

r500 = calculate_aqi({"pm25": 500.0})
assert r500["aqi"] == 500, "PM2.5=500 should give AQI=500"

print("ALL SMOKE TESTS PASSED")
