import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class SnowDayCalculator:
    """
    Fixed Snow Day Calculator using NWS Gridpoint Data.
    Calculates probabilities for the next four weekdays, skipping weekends.
    Properly aligns hourly forecast data for accurate scoring.
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
        """Fetch hourly forecast and alerts from NWS."""
        try:
            if not self.get_coordinates_from_zip():
                return False
            
            metadata = self.get_location_metadata()
            if not metadata:
                return False
            
            # URLs
            hourly_url = metadata['forecastHourly']
            alerts_url = f"{self.base_url}/alerts/active?point={self.lat},{self.lon}"
            
            # Hourly forecast - this has all the data we need
            hourly_response = requests.get(hourly_url, headers=self.headers, timeout=15)
            if hourly_response.status_code == 200:
                self.hourly_forecast = hourly_response.json()['properties']['periods']
            else:
                self.error_message = "Failed to fetch hourly forecast"
                return False
            
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
        """Score based on snow in forecast descriptions."""
        score = 0.0
        if not day_hours:
            return 0.0
        
        snow_hours = 0
        heavy_snow_hours = 0
        
        for period in day_hours:
            desc = period.get('shortForecast', '').lower()
            detailed = period.get('detailedForecast', '').lower()
            
            # Check for snow mentions
            if 'snow' in desc or 'snow' in detailed:
                snow_hours += 1
                if 'heavy' in detailed or 'significant' in detailed:
                    heavy_snow_hours += 1
        
        # Score based on duration and intensity
        if heavy_snow_hours >= 6:
            score += 30
        elif heavy_snow_hours >= 3:
            score += 20
        elif heavy_snow_hours >= 1:
            score += 10
        
        if snow_hours >= 12:
            score += 20
        elif snow_hours >= 8:
            score += 12
        elif snow_hours >= 4:
            score += 6
        
        return score
    
    def analyze_temperature(self, day_hours: List[Dict]) -> float:
        """Score based on morning, overnight, and wind chill temperatures."""
        score = 0.0
        if not day_hours:
            return 0.0
        
        morning_temps = []
        overnight_temps = []
        wind_chills = []
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            hour = dt.hour
            temp = period['temperature']
            
            # NWS returns wind chill in Fahrenheit directly (no conversion needed)
            wind_chill = period.get('windChill')
            
            # Categorize by time of day
            if 0 <= hour <= 6:
                overnight_temps.append(temp)
            if 6 <= hour <= 9:
                morning_temps.append(temp)
            if wind_chill is not None:
                wind_chills.append(wind_chill)
        
        # Morning temperature scoring
        if morning_temps:
            avg_morning = sum(morning_temps) / len(morning_temps)
            if avg_morning < 0:
                score += 20
            elif avg_morning < 10:
                score += 15
            elif avg_morning < 20:
                score += 8
            elif avg_morning < 32:
                score += 3
        
        # Overnight temperature scoring
        if overnight_temps:
            min_overnight = min(overnight_temps)
            if min_overnight < -10:
                score += 12
            elif min_overnight < 0:
                score += 8
            elif min_overnight < 15:
                score += 4
        
        # Wind chill scoring
        if wind_chills:
            min_wc = min(wind_chills)
            if min_wc < -20:
                score += 15
            elif min_wc < -10:
                score += 10
            elif min_wc < 0:
                score += 5
        
        return score
    
    def analyze_wind(self, day_hours: List[Dict]) -> float:
        """Score based on wind speed and gusts."""
        score = 0.0
        if not day_hours:
            return 0.0
        
        wind_speeds = []
        wind_gusts = []
        high_wind_hours = 0
        
        for period in day_hours:
            wind_speed = period.get('windSpeed')
            wind_gust = period.get('windGust')
            
            if wind_speed:
                # windSpeed is a string like "10 mph", extract number
                speed_val = self._extract_number(wind_speed)
                if speed_val:
                    wind_speeds.append(speed_val)
                    if speed_val > 20:
                        high_wind_hours += 1
            
            if wind_gust:
                gust_val = self._extract_number(wind_gust)
                if gust_val:
                    wind_gusts.append(gust_val)
        
        if not wind_speeds:
            return 0.0
        
        max_wind = max(wind_speeds)
        max_gust = max(wind_gusts) if wind_gusts else 0
        
        # Wind speed scoring
        if max_wind >= 35:
            score += 25
        elif max_wind >= 30:
            score += 18
        elif max_wind >= 25:
            score += 12
        elif max_wind >= 20:
            score += 6
        
        # Gust scoring
        if max_gust >= 50:
            score += 12
        elif max_gust >= 40:
            score += 8
        elif max_gust >= 35:
            score += 4
        
        # Sustained high wind scoring
        if high_wind_hours >= 6:
            score += 5
        
        return score
    
    def analyze_visibility(self, day_hours: List[Dict]) -> float:
        """Score based on visibility conditions."""
        score = 0.0
        if not day_hours:
            return 0.0
        
        visibilities = []
        poor_vis_hours = 0
        
        for period in day_hours:
            # Visibility is a string like "10 mi", extract number
            vis_str = period.get('visibility', '')
            vis_val = self._extract_number(vis_str)
            if vis_val:
                visibilities.append(vis_val)
                if vis_val < 0.5:
                    poor_vis_hours += 1
        
        if not visibilities:
            return 0.0
        
        min_vis = min(visibilities)
        
        # Visibility scoring
        if min_vis < 0.25:
            score += 20
        elif min_vis < 0.5:
            score += 15
        elif min_vis < 1.0:
            score += 10
        elif min_vis < 2.0:
            score += 5
        
        # Poor visibility hours
        if poor_vis_hours >= 4:
            score += 8
        
        return score
    
    def analyze_precipitation_type(self, day_hours: List[Dict]) -> float:
        """Score based on freezing rain, sleet, and other hazardous precip."""
        score = 0.0
        if not day_hours:
            return 0.0
        
        for period in day_hours:
            desc = period.get('shortForecast', '').lower()
            detailed = period.get('detailedForecast', '').lower()
            
            if 'freezing rain' in detailed or 'freezing rain' in desc:
                score += 35
            elif 'sleet' in detailed or 'ice pellets' in detailed:
                score += 20
            elif 'freezing drizzle' in detailed:
                score += 15
        
        return score
    
    def analyze_alerts(self) -> float:
        """Score based on active weather alerts."""
        score = 0.0
        if not self.alerts:
            return 0.0
        
        for alert in self.alerts:
            event = alert['properties'].get('event', '')
            if 'Blizzard Warning' in event:
                score += 40
            elif 'Ice Storm Warning' in event:
                score += 38
            elif 'Winter Storm Warning' in event:
                score += 30
            elif 'Wind Chill Warning' in event:
                score += 20
            elif 'Winter Weather Advisory' in event:
                score += 12
            elif 'Wind Chill Advisory' in event:
                score += 8
        
        return min(score, 40.0)
    
    def analyze_timing(self, day_hours: List[Dict]) -> float:
        """Bonus points if snow occurs during peak impact times."""
        score = 0.0
        if not day_hours:
            return 0.0
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            hour = dt.hour
            desc = period.get('shortForecast', '').lower()
            
            # Morning commute (5-9am)
            if 5 <= hour <= 9 and 'snow' in desc:
                score += 8
            
            # Overnight accumulation (10pm-4am)
            if hour >= 22 or hour <= 4:
                if 'snow' in desc or 'blizzard' in desc:
                    score += 5
        
        return score
    
    def analyze_road_conditions(self, day_hours: List[Dict]) -> float:
        """Score based on freeze/thaw cycles and road impact."""
        score = 0.0
        if not day_hours:
            return 0.0
        
        temps = [p['temperature'] for p in day_hours[:12]]
        if not temps:
            return 0.0
        
        avg_temp = sum(temps) / len(temps)
        
        # Consistently cold temps
        if avg_temp < 10:
            score += 8
        elif avg_temp < 15:
            score += 5
        
        # Freeze/thaw cycle (most dangerous)
        temps_above = sum(1 for t in temps if t > 32)
        temps_below = sum(1 for t in temps if t <= 32)
        if temps_above > 0 and temps_below > 0:
            score += 6
        
        return score
    
    @staticmethod
    def _extract_number(s: str) -> Optional[float]:
        """Extract numeric value from strings like '10 mph' or '5 mi'."""
        try:
            return float(''.join(c for c in s.split()[0] if c.isdigit() or c == '.'))
        except (ValueError, IndexError):
            return None

    # -------------------------
    # Main per-day calculation
    # -------------------------
    
    def calculate_next_weekday_probabilities(self) -> Dict:
        """Calculate snow day probability for next 4 weekdays."""
        if not self.fetch_weather_data():
            return {
                'success': False,
                'error': self.error_message,
                'probabilities': []
            }
        
        if not self.hourly_forecast:
            return {
                'success': False,
                'error': 'No hourly forecast data available',
                'probabilities': []
            }
        
        results = []
        counted_days = 0
        today = datetime.now().date()
        
        # Group hourly periods by date
        periods_by_date = {}
        for period in self.hourly_forecast:
            dt = datetime.fromisoformat(period['startTime'])
            day_date = dt.date()
            if day_date not in periods_by_date:
                periods_by_date[day_date] = []
            periods_by_date[day_date].append(period)
        
        # Calculate for each future weekday
        for day_date in sorted(periods_by_date.keys()):
            weekday_num = day_date.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
            
            # Skip past days and weekends
            if day_date <= today or weekday_num >= 5:
                continue
            
            day_hours = periods_by_date[day_date]
            
            # Calculate component scores
            snowfall_score = self.analyze_snowfall(day_hours)
            temp_score = self.analyze_temperature(day_hours)
            wind_score = self.analyze_wind(day_hours)
            visibility_score = self.analyze_visibility(day_hours)
            precip_score = self.analyze_precipitation_type(day_hours)
            alerts_score = self.analyze_alerts()
            timing_score = self.analyze_timing(day_hours)
            road_score = self.analyze_road_conditions(day_hours)
            
            total_score = (
                snowfall_score +
                temp_score +
                wind_score +
                visibility_score +
                precip_score +
                alerts_score +
                timing_score +
                road_score
            )
            
            # Convert score to probability using logistic function
            # Max theoretical score: 30+20+25+20+35+40+8+8 = 186
            # Calibrated so 50 points = ~50% probability
            probability = (100 / (1 + (2.7183 ** (-0.05 * (total_score - 50)))))
            probability = max(1, min(99, int(probability)))
            
            # Likelihood label
            if probability < 15:
                likelihood = "VERY UNLIKELY"
            elif probability < 35:
                likelihood = "UNLIKELY"
            elif probability < 55:
                likelihood = "POSSIBLE"
            elif probability < 75:
                likelihood = "LIKELY"
            else:
                likelihood = "VERY LIKELY"
            
            results.append({
                'date': day_date.strftime('%Y-%m-%d'),
                'weekday': day_date.strftime('%A'),
                'probability': probability,
                'likelihood': likelihood,
                'score_breakdown': {
                    'snowfall': snowfall_score,
                    'temperature': temp_score,
                    'wind': wind_score,
                    'visibility': visibility_score,
                    'precipitation_type': precip_score,
                    'alerts': alerts_score,
                    'timing': timing_score,
                    'road_conditions': road_score,
                    'total': total_score
                }
            })
            
            counted_days += 1
            if counted_days >= 4:
                break
        
        return {
            'success': True,
            'location': self.location_name,
            'zipcode': self.zipcode,
            'probabilities': results,
            'timestamp': datetime.now().strftime('%Y-%m-%d %I:%M %p')
        }


def get_snow_day_probabilities(zipcode: str) -> Dict:
    """Convenience function to get snow day probabilities."""
    calculator = SnowDayCalculator(zipcode)
    return calculator.calculate_next_weekday_probabilities()