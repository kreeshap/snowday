import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class SnowDayCalculator:
    """
    Full-featured Snow Day Calculator using NWS Gridpoint Data.
    Calculates probabilities for the next four weekdays, skipping weekends.
    Uses full scoring for snowfall, temperature, wind, visibility, precipitation, alerts, timing, and roads.
    """
    
    def __init__(self, zipcode: str):
        self.zipcode = zipcode
        self.lat = None
        self.lon = None
        self.location_name = None
        self.base_url = "https://api.weather.gov"
        self.headers = {
            'User-Agent': '(SnowDayCalculator, contact@example.com)',
            'Accept': 'application/json'
        }
        self.gridpoint_data = None
        self.forecast_data = None
        self.hourly_forecast = None
        self.alerts = None
        self.error_message = None

    # -------------------------
    # Data fetching
    # -------------------------
    
    def get_coordinates_from_zip(self) -> bool:
        url = f"https://api.zippopotam.us/us/{self.zipcode}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.lat = float(data['places'][0]['latitude'])
                self.lon = float(data['places'][0]['longitude'])
                self.location_name = f"{data['places'][0]['place name']}, {data['places'][0]['state abbreviation']}"
                return True
            else:
                self.error_message = f"Invalid ZIP code: {self.zipcode}"
                return False
        except Exception as e:
            self.error_message = f"Failed to geocode ZIP code: {str(e)}"
            return False
    
    def get_location_metadata(self) -> Optional[Dict]:
        try:
            url = f"{self.base_url}/points/{self.lat},{self.lon}"
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code != 200:
                self.error_message = "Failed to get location metadata"
                return None
            return response.json()['properties']
        except Exception as e:
            self.error_message = f"Error fetching location metadata: {str(e)}"
            return None
    
    def fetch_weather_data(self) -> bool:
        """Fetch all NWS data: gridpoint, forecast, hourly, alerts."""
        try:
            if not self.get_coordinates_from_zip():
                return False
            
            metadata = self.get_location_metadata()
            if not metadata:
                return False
            
            # URLs
            grid_url = metadata['forecastGridData']
            forecast_url = metadata['forecast']
            hourly_url = metadata['forecastHourly']
            alerts_url = f"{self.base_url}/alerts/active?point={self.lat},{self.lon}"
            
            # Gridpoint data
            grid_response = requests.get(grid_url, headers=self.headers, timeout=15)
            if grid_response.status_code == 200:
                self.gridpoint_data = grid_response.json()['properties']
            
            # Daily forecast periods
            forecast_response = requests.get(forecast_url, headers=self.headers, timeout=15)
            if forecast_response.status_code == 200:
                self.forecast_data = forecast_response.json()['properties']['periods']
            
            # Hourly forecast
            hourly_response = requests.get(hourly_url, headers=self.headers, timeout=15)
            if hourly_response.status_code == 200:
                self.hourly_forecast = hourly_response.json()['properties']['periods']
            
            # Alerts
            alerts_response = requests.get(alerts_url, headers=self.headers, timeout=15)
            if alerts_response.status_code == 200:
                self.alerts = alerts_response.json()['features']
            
            return True
        except Exception as e:
            self.error_message = f"Error fetching weather data: {str(e)}"
            return False

    # -------------------------
    # Analysis functions
    # -------------------------

    def analyze_snowfall(self, day_hours: List[Dict]) -> float:
        score = 0.0
        if self.gridpoint_data and 'snowfallAmount' in self.gridpoint_data:
            values = self.gridpoint_data['snowfallAmount']['values']
            if values:
                snow_amounts = []
                # Match values to this day
                for v in values[:24*len(day_hours)//24]:
                    if v['value']:
                        snow_amounts.append(v['value'] * 0.0393701)  # meters to inches
                if snow_amounts:
                    total_snow = sum(snow_amounts)
                    max_snow = max(snow_amounts)
                    if total_snow >= 12: score += 30
                    elif total_snow >= 8: score += 25
                    elif total_snow >= 6: score += 20
                    elif total_snow >= 4: score += 12
                    elif total_snow >= 2: score += 5
                    if max_snow >= 2: score += 10
                    elif max_snow >= 1: score += 5
        return score
    
    def analyze_temperature(self, day_hours: List[Dict]) -> float:
        score = 0.0
        if not day_hours:
            return 0.0
        
        morning_temps = []
        overnight_temps = []
        wind_chills = []
        for period in day_hours:
            hour = datetime.fromisoformat(period['startTime']).hour
            temp = period['temperature']
            wind_chill = period.get('windChill', {})
            if 0 <= hour <= 6: overnight_temps.append(temp)
            if 6 <= hour <= 9: morning_temps.append(temp)
            if wind_chill and wind_chill.get('value'):
                wc_temp = wind_chill['value'] * 9/5 + 32
                wind_chills.append(wc_temp)
        
        if morning_temps:
            avg_morning = sum(morning_temps)/len(morning_temps)
            if avg_morning < 0: score += 20
            elif avg_morning < 10: score += 15
            elif avg_morning < 20: score += 8
            elif avg_morning < 32: score += 3
            if avg_morning < 15: score += 5
        
        if overnight_temps:
            min_overnight = min(overnight_temps)
            if min_overnight < -10: score += 12
            elif min_overnight < 0: score += 8
            elif min_overnight < 15: score += 4
        
        if wind_chills:
            min_wc = min(wind_chills)
            if min_wc < -20: score += 15
            elif min_wc < -10: score += 10
            elif min_wc < 0: score += 5
        
        return score
    
    def analyze_wind(self, day_hours: List[Dict]) -> float:
        score = 0.0
        if not self.gridpoint_data:
            return 0.0
        wind_speeds = self.gridpoint_data.get('windSpeed', {}).get('values', [])
        wind_gusts = self.gridpoint_data.get('windGust', {}).get('values', [])
        if not wind_speeds: return 0.0
        
        max_wind = 0
        max_gust = 0
        sustained_high_wind = 0
        for i, wind in enumerate(wind_speeds[:len(day_hours)]):
            if wind['value']:
                mph = wind['value'] * 0.621371
                max_wind = max(max_wind, mph)
                if mph > 20: sustained_high_wind += 1
        for gust in wind_gusts[:len(day_hours)]:
            if gust['value']:
                max_gust = max(max_gust, gust['value'] * 0.621371)
        
        if max_wind >= 35: score += 25
        elif max_wind >= 30: score += 18
        elif max_wind >= 25: score += 12
        elif max_wind >= 20: score += 6
        if max_gust >= 50: score += 12
        elif max_gust >= 40: score += 8
        elif max_gust >= 35: score += 4
        if sustained_high_wind >= 6: score += 5
        return score
    
    def analyze_visibility(self, day_hours: List[Dict]) -> float:
        score = 0.0
        if not self.gridpoint_data: return 0.0
        visibility = self.gridpoint_data.get('visibility', {}).get('values', [])
        if not visibility: return 0.0
        min_vis = float('inf')
        poor_vis_hours = 0
        for vis in visibility[:len(day_hours)]:
            if vis['value']:
                miles = vis['value'] * 0.000621371
                min_vis = min(min_vis, miles)
                if miles < 0.5: poor_vis_hours += 1
        if min_vis == float('inf'): return 0.0
        if min_vis < 0.25: score += 20
        elif min_vis < 0.5: score += 15
        elif min_vis < 1.0: score += 10
        elif min_vis < 2.0: score += 5
        if poor_vis_hours >= 4: score += 8
        return score
    
    def analyze_precipitation_type(self, day_hours: List[Dict]) -> float:
        score = 0.0
        if not self.gridpoint_data: return 0.0
        ice_accum = self.gridpoint_data.get('iceAccumulation', {}).get('values', [])
        max_ice = 0
        for ice in ice_accum[:len(day_hours)]:
            if ice['value']: max_ice = max(max_ice, ice['value'] * 0.0393701)
        if max_ice > 0.5: score += 35
        elif max_ice > 0.25: score += 25
        elif max_ice > 0.1: score += 15
        elif max_ice > 0: score += 8
        if self.forecast_data:
            for i, period in enumerate(self.forecast_data[:4]):
                desc = period.get('detailedForecast','').lower()
                if 'freezing rain' in desc or 'freezing drizzle' in desc: score += 15; break
                if 'sleet' in desc or 'ice pellets' in desc: score += 10; break
                if i == 0 and ('rain' in desc and 'snow' not in desc): score += 5
                if i >= 2 and 'rain' in desc: score += 3
        return score
    
    def analyze_alerts(self) -> float:
        score = 0.0
        if not self.alerts: return 0.0
        for alert in self.alerts:
            event = alert['properties']['event']
            if 'Blizzard Warning' in event: score += 40
            elif 'Ice Storm Warning' in event: score += 38
            elif 'Winter Storm Warning' in event: score += 30
            elif 'Wind Chill Warning' in event: score += 20
            elif 'Winter Weather Advisory' in event: score += 12
            elif 'Wind Chill Advisory' in event: score += 8
        return min(score, 40.0)
    
    def analyze_timing(self, day_hours: List[Dict]) -> float:
        score = 0.0
        for period in day_hours:
            hour = datetime.fromisoformat(period['startTime']).hour
            desc = period.get('shortForecast','').lower()
            if 5 <= hour <= 9 and 'snow' in desc: score += 8
            if 22 <= hour or hour <= 4:
                if 'snow' in desc or 'blizzard' in desc: score += 5
        return score
    
    def analyze_road_conditions(self, day_hours: List[Dict]) -> float:
        score = 0.0
        if not day_hours: return 0.0
        temps = [p['temperature'] for p in day_hours[:12]]
        avg_temp = sum(temps)/len(temps) if temps else 0
        if avg_temp < 10: score += 8
        elif avg_temp < 15: score += 5
        temps_above = [t for t in temps if t>32]
        temps_below = [t for t in temps if t<=32]
        if len(temps_above)>0 and len(temps_below)>0: score += 6
        return score

    # -------------------------
    # Main per-day calculation
    # -------------------------
    
    def calculate_next_weekday_probabilities(self) -> Dict:
        if not self.fetch_weather_data():
            return {'success': False, 'error': self.error_message, 'probabilities': []}
        
        results = []
        counted_days = 0
        today = datetime.now().date()
        
        # Split hourly forecast by date
        periods_by_date = {}
        for period in self.hourly_forecast:
            dt = datetime.fromisoformat(period['startTime'])
            day_date = dt.date()
            if day_date not in periods_by_date:
                periods_by_date[day_date] = []
            periods_by_date[day_date].append(period)
        
        # Loop through sorted dates
        for day_date in sorted(periods_by_date.keys()):
            weekday = day_date.weekday()
            if day_date <= today or weekday >= 5:  # skip past and weekends
                continue
            day_hours = periods_by_date[day_date]
            
            # Full scoring
            total_score = (
                self.analyze_snowfall(day_hours) +
                self.analyze_temperature(day_hours) +
                self.analyze_wind(day_hours) +
                self.analyze_visibility(day_hours) +
                self.analyze_precipitation_type(day_hours) +
                self.analyze_alerts() +
                self.analyze_timing(day_hours) +
                self.analyze_road_conditions(day_hours)
            )
            
            # Logistic probability scaling
            probability = (100 / (1 + (2.7183 ** (-0.05 * (total_score - 50)))))
            probability = max(1, min(99, int(probability)))
            
            if probability < 15: likelihood = "VERY UNLIKELY"
            elif probability < 35: likelihood = "UNLIKELY"
            elif probability < 55: likelihood = "POSSIBLE"
            elif probability < 75: likelihood = "LIKELY"
            else: likelihood = "VERY LIKELY"
            
            results.append({
                'date': day_date.strftime('%Y-%m-%d'),
                'weekday': day_date.strftime('%A'),
                'probability': probability,
                'likelihood': likelihood
            })
            
            counted_days += 1
            if counted_days >= 4: break
        
        return {
            'success': True,
            'location': self.location_name,
            'zipcode': self.zipcode,
            'probabilities': results,
            'timestamp': datetime.now().strftime('%Y-%m-%d %I:%M %p')
        }

# -------------------------
# Convenience function
# -------------------------

def get_snow_day_probabilities(zipcode: str) -> Dict:
    calculator = SnowDayCalculator(zipcode)
    return calculator.calculate_next_weekday_probabilities()
