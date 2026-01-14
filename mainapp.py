import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

class SnowDayCalculator:
    
    def __init__(self, zipcode: str):
        self.zipcode = zipcode
        self.lat = None
        self.lon = None
        self.base_url = "https://api.weather.gov"
        self.headers = {
            'User-Agent': '(SnowDayCalculator, contact@example.com)',
            'Accept': 'application/json'
        }
        self.gridpoint_data = None
        self.forecast_data = None
        self.hourly_forecast = None
        self.alerts = None
        
    def get_coordinates_from_zip(self) -> Tuple[float, float]:
        url = f"https://api.zippopotam.us/us/{self.zipcode}"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.lat = float(data['places'][0]['latitude'])
                self.lon = float(data['places'][0]['longitude'])
                return self.lat, self.lon
            else:
                raise Exception(f"wrong zipcode: {self.zipcode}")
        except Exception as e:
            raise Exception(f"failed to geocode ur zip code: {e}")
    
    def get_location_metadata(self) -> Dict:
        url = f"{self.base_url}/points/{self.lat},{self.lon}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            raise Exception(f"failed to get location data: {response.status_code}")
        
        return response.json()
    
    def fetch_weather_data(self):
        print("cookin up...")
        
        self.get_coordinates_from_zip()
        
        metadata = self.get_location_metadata()
        properties = metadata['properties']
        
        # Get gridpoint forecast URL
        gridpoint_url = properties['forecastGridData']
        forecast_url = properties['forecast']
        hourly_url = properties['forecastHourly']
        
        # Fetch gridpoint data (detailed)
        grid_response = requests.get(gridpoint_url, headers=self.headers)
        self.gridpoint_data = grid_response.json()['properties']
        
        # Fetch forecast data
        forecast_response = requests.get(forecast_url, headers=self.headers)
        self.forecast_data = forecast_response.json()['properties']['periods']
        
        # Fetch hourly forecast
        hourly_response = requests.get(hourly_url, headers=self.headers)
        self.hourly_forecast = hourly_response.json()['properties']['periods']
        
        # Fetch active alerts
        alert_url = f"{self.base_url}/alerts/active?point={self.lat},{self.lon}"
        alert_response = requests.get(alert_url, headers=self.headers)
        self.alerts = alert_response.json()['features']
    
    def analyze_snowfall(self) -> float:
        score = 0.0
        
        if self.gridpoint_data and 'snowfallAmount' in self.gridpoint_data:
            values = self.gridpoint_data['snowfallAmount']['values']
            if values:
                # Get snowfall amounts over time to calculate rate
                snow_amounts = []
                for v in values[:24]:  # Next 24 hours
                    if v['value']:
                        snow_amounts.append(v['value'] * 0.0393701)  # mm to inches
                
                if snow_amounts:
                    total_snow = sum(snow_amounts)
                    max_snow = max(snow_amounts)
                    
                    # Total accumulation scoring
                    if total_snow >= 12:
                        score += 30.0
                    elif total_snow >= 8:
                        score += 25.0
                    elif total_snow >= 6:
                        score += 20.0
                    elif total_snow >= 4:
                        score += 12.0
                    elif total_snow >= 2:
                        score += 5.0
                    
                    # Snowfall rate (intensity)
                    if max_snow >= 2:  # 2+ inches per hour
                        score += 10.0
                    elif max_snow >= 1:
                        score += 5.0
        
        return score
    
    def analyze_temperature(self) -> float:
        """Analyze all temperature factors"""
        score = 0.0
        
        if not self.hourly_forecast:
            return 0
        
        morning_temps = []
        overnight_temps = []
        wind_chills = []
        
        for period in self.hourly_forecast[:24]:
            hour = datetime.fromisoformat(period['startTime']).hour
            temp = period['temperature']
            wind_chill = period.get('windChill', {})
            
            if 0 <= hour <= 6:
                overnight_temps.append(temp)
            if 6 <= hour <= 9:
                morning_temps.append(temp)
            
            # Wind chill
            if wind_chill and wind_chill.get('value'):
                wc_temp = wind_chill['value'] * 9/5 + 32  # C to F
                wind_chills.append(wc_temp)
        
        if morning_temps:
            avg_morning = sum(morning_temps) / len(morning_temps)
            
            # Morning bus temperature critical
            if avg_morning < 0:
                score += 20.0
            elif avg_morning < 10:
                score += 15.0
            elif avg_morning < 20:
                score += 8.0
            elif avg_morning < 32:
                score += 3.0
        
        if overnight_temps:
            min_overnight = min(overnight_temps)
            
            # Overnight low affects road treatment
            if min_overnight < -10:
                score += 12.0
            elif min_overnight < 0:
                score += 8.0
            elif min_overnight < 15:
                score += 4.0
        
        # Wind chill danger
        if wind_chills:
            min_wc = min(wind_chills)
            if min_wc < -20:
                score += 15.0
            elif min_wc < -10:
                score += 10.0
            elif min_wc < 0:
                score += 5.0
        
        # Salt effectiveness (below 15F salt becomes less effective)
        if morning_temps and avg_morning < 15:
            score += 5.0
        
        return score
    
    def analyze_wind(self) -> float:
        """Analyze wind conditions and impacts"""
        score = 0.0
        
        if not self.gridpoint_data:
            return 0
        
        wind_speeds = self.gridpoint_data.get('windSpeed', {}).get('values', [])
        wind_gusts = self.gridpoint_data.get('windGust', {}).get('values', [])
        
        if not wind_speeds:
            return 0
        
        max_wind = 0
        max_gust = 0
        sustained_high_wind = 0
        
        for i, wind in enumerate(wind_speeds[:24]):
            if wind['value']:
                mph = wind['value'] * 0.621371
                max_wind = max(max_wind, mph)
                if mph > 20:
                    sustained_high_wind += 1
        
        for gust in wind_gusts[:24]:
            if gust['value']:
                max_gust = max(max_gust, gust['value'] * 0.621371)
        
        # Blizzard conditions (35+ mph with snow)
        if max_wind >= 35:
            score += 25.0
        elif max_wind >= 30:
            score += 18.0
        elif max_wind >= 25:
            score += 12.0
        elif max_wind >= 20:
            score += 6.0
        
        # Dangerous gusts
        if max_gust >= 50:
            score += 12.0
        elif max_gust >= 40:
            score += 8.0
        elif max_gust >= 35:
            score += 4.0
        
        # Sustained high winds increase drifting/blowing snow
        if sustained_high_wind >= 6:
            score += 5.0
        
        return score
    
    def analyze_visibility(self) -> float:
        """Analyze visibility conditions"""
        score = 0.0
        
        if not self.gridpoint_data:
            return 0
        
        visibility = self.gridpoint_data.get('visibility', {}).get('values', [])
        
        if not visibility:
            return 0
        
        min_vis = float('inf')
        poor_vis_hours = 0
        
        for vis in visibility[:24]:
            if vis['value']:
                miles = vis['value'] * 0.000621371
                min_vis = min(min_vis, miles)
                if miles < 0.5:
                    poor_vis_hours += 1
        
        if min_vis == float('inf'):
            return 0
        
        # Whiteout/near-zero visibility
        if min_vis < 0.25:
            score += 20.0
        elif min_vis < 0.5:
            score += 15.0
        elif min_vis < 1.0:
            score += 10.0
        elif min_vis < 2.0:
            score += 5.0
        
        # Extended poor visibility
        if poor_vis_hours >= 4:
            score += 8.0
        
        return score
    
    def analyze_precipitation_type(self) -> float:
        """Analyze dangerous precipitation types"""
        score = 0.0
        
        if not self.gridpoint_data:
            return 0
        
        ice_accum = self.gridpoint_data.get('iceAccumulation', {}).get('values', [])
        
        # Ice accumulation - extremely dangerous
        max_ice = 0
        for ice in ice_accum[:24]:
            if ice['value']:
                max_ice = max(max_ice, ice['value'] * 0.0393701)
        
        if max_ice > 0.5:
            score += 35.0  # Severe ice storm
        elif max_ice > 0.25:
            score += 25.0  # Significant ice
        elif max_ice > 0.1:
            score += 15.0  # Light ice
        elif max_ice > 0:
            score += 8.0
        
        # Check forecasts for mixed precipitation
        has_freezing_rain = False
        has_sleet = False
        has_rain_before = False
        has_rain_after = False
        
        for i, period in enumerate(self.forecast_data[:4]):
            desc = period.get('detailedForecast', '').lower()
            
            if 'freezing rain' in desc or 'freezing drizzle' in desc:
                has_freezing_rain = True
                score += 15.0
            
            if 'sleet' in desc or 'ice pellets' in desc:
                has_sleet = True
                score += 10.0
            
            if i == 0 and ('rain' in desc and 'snow' not in desc):
                has_rain_before = True
                score += 5.0  # Rain before snow complicates treatment
            
            if i >= 2 and ('rain' in desc and temp > 32):
                has_rain_after = True
                score += 3.0  # Refreeze risk
        
        return score
    
    def analyze_alerts(self) -> float:
        """Analyze official weather alerts"""
        score = 0.0
        
        if not self.alerts:
            return 0
        
        for alert in self.alerts:
            event = alert['properties']['event']
            
            if 'Blizzard Warning' in event:
                score += 40.0
            elif 'Ice Storm Warning' in event:
                score += 38.0
            elif 'Winter Storm Warning' in event:
                score += 30.0
            elif 'Wind Chill Warning' in event:
                score += 20.0
            elif 'Winter Weather Advisory' in event:
                score += 12.0
            elif 'Wind Chill Advisory' in event:
                score += 8.0
        
        return min(score, 40.0)  # Cap alert contribution
    
    def analyze_timing(self) -> float:
        """Analyze timing of weather events"""
        score = 0.0
        
        if not self.hourly_forecast:
            return 0
        
        # Check if worst conditions hit during critical times
        critical_morning = False
        overnight_event = False
        
        for period in self.hourly_forecast[:24]:
            hour = datetime.fromisoformat(period['startTime']).hour
            desc = period.get('shortForecast', '').lower()
            
            # Snow during morning commute (5 AM - 9 AM)
            if 5 <= hour <= 9 and 'snow' in desc:
                critical_morning = True
            
            # Heavy snow overnight (makes morning prep harder)
            if 22 <= hour or hour <= 4:
                if 'snow' in desc or 'blizzard' in desc:
                    overnight_event = True
        
        if critical_morning:
            score += 8.0
        if overnight_event:
            score += 5.0
        
        return score
    
    def analyze_road_conditions(self) -> float:
        """Estimate road condition impacts"""
        score = 0.0
        
        # Temperature for road treatment
        if self.hourly_forecast:
            temps = [p['temperature'] for p in self.hourly_forecast[:12]]
            avg_temp = sum(temps) / len(temps)
            
            # Below 15F, salt doesn't work well
            if avg_temp < 10:
                score += 8.0
            elif avg_temp < 15:
                score += 5.0
            
            # Check for refreeze potential
            temps_above = [t for t in temps if t > 32]
            temps_below = [t for t in temps if t <= 32]
            
            if len(temps_above) > 0 and len(temps_below) > 0:
                score += 6.0  # Melting then refreezing
        
        return score
    
    def calculate_snow_day_probability(self) -> Dict:
        """Calculate overall snow day probability with weighted factors"""
        
        # Analyze all factors
        snowfall_score = self.analyze_snowfall()
        temp_score = self.analyze_temperature()
        wind_score = self.analyze_wind()
        visibility_score = self.analyze_visibility()
        precip_score = self.analyze_precipitation_type()
        alert_score = self.analyze_alerts()
        timing_score = self.analyze_timing()
        road_score = self.analyze_road_conditions()
        
        # Calculate total with diminishing returns
        total_score = (
            snowfall_score +
            temp_score +
            wind_score +
            visibility_score +
            precip_score +
            alert_score +
            timing_score +
            road_score
        )
        
        # Apply curve to make extreme weather more decisive
        # Use logistic function for realistic probability
        probability = (100 / (1 + (2.7183 ** (-0.05 * (total_score - 50))))) 
        
        # Cap between 1 and 99
        probability = max(1, min(99, int(probability)))
        
        # Determine likelihood
        if probability < 15:
            likelihood = "boi u got school dont play"
        elif probability < 35:
            likelihood = "boi u got like the slighest chance"
        elif probability < 55:
            likelihood = "flip a coin and thats ur chance u feel me"
        elif probability < 75:
            likelihood = "perhaps..."
        else:
            likelihood = "atp if u don't ur school is ass"
        
        return {
            'probability': probability,
            'likelihood': likelihood
        }
    
    def generate_report(self):
        """Generate snow day probability report"""
        self.fetch_weather_data()
        result = self.calculate_snow_day_probability()
        
        print("\n" + "=" * 50)
        print("         SNOW DAY PROBABILITY CALCULATOR")
        print("=" * 50)
        print(f"\nZIP Code: {self.zipcode}")
        print(f"Date: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")
        print("\n" + "=" * 50)
        print(f"\n  PROBABILITY: {result['probability']}%")
        print(f"  ASSESSMENT: {result['likelihood']}")
        print("\n" + "=" * 50)
        print("=" * 50 + "\n")


if __name__ == "__main__":
    print("\n       SNOW DAY CALCULATOR\n")
    
    try:
        zipcode = input("enter yo ZIP code: ").strip()
        
        if not zipcode.isdigit() or len(zipcode) != 5:
            print("\nError: for the love of god please enter a valid  ZIP code")
        else:
            calculator = SnowDayCalculator(zipcode)
            calculator.generate_report()
        
    except Exception as e:
        print(f"\nError: {e}")