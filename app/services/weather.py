"""Open-Meteo forecast (forecast only - never a guarantee, never a safety certification)."""
import httpx


def forecast(lat: float, lon: float, days: int = 3) -> dict:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid coordinates")
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=10, params={
            "latitude": lat, "longitude": lon, "forecast_days": max(1, min(days, 7)), "timezone": "auto",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        return {"available": False, "error": f"Weather service unavailable: {e}"}
    d = r.json()["daily"]
    out = [{"date": d["time"][i], "tmax_c": d["temperature_2m_max"][i], "tmin_c": d["temperature_2m_min"][i],
            "rain_probability_pct": d["precipitation_probability_max"][i], "rain_mm": d["precipitation_sum"][i]}
           for i in range(len(d["time"]))]
    risky = [x["date"] for x in out if (x["rain_probability_pct"] or 0) >= 60]
    return {"available": True, "days": out, "rain_risk_dates": risky,
            "disclaimer": "Forecast only. Site professional must review work conditions."}
