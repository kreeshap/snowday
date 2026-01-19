import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

class ImprovedSnowDayCalculator:
    """
    Enhanced Snow Day Calculator using NWS Gridpoint Data.
    Focuses on timing and accumulation rate as primary factors.
    More conservative probability estimates based on actual school closure patterns.
    """
    
    def __init__(self, zipcode: str):
        self.zipcode = zipcode
        self.lat = None
        self.lon = None
        self.location_name = None
        self.base_url = "https://api.weather.gov"
        self.headers = {
            'User-Agent': '(ImprovedSnowDayCalculator, contact@example.com)',
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
            
            hourly_url = metadata['forecastHourly']
            alerts_url = f"{self.base_url}/alerts/active?point={self.lat},{self.lon}"
            
            hourly_response = requests.get(hourly_url, headers=self.headers, timeout=15)
            if hourly_response.status_code == 200:
                self.hourly_forecast = hourly_response.json()['properties']['periods']
            else:
                self.error_message = "Failed to fetch hourly forecast"
                return False
            
            alerts_response = requests.get(alerts_url, headers=self.headers, timeout=15)
            if alerts_response.status_code == 200:
                self.alerts = alerts_response.json()['features']
            
            return True
        except Exception as e:
            self.error_message = f"Error fetching weather data: {str(e)}"
            return False

    # -------------------------
    # Analysis functions (rewritten for timing priority)
    # -------------------------

    def calculate_accumulation_rate(self, day_hours: List[Dict]) -> Dict:
        """
        Calculate snowfall accumulation rate - the CRITICAL factor.
        Returns accumulation by 3-hour windows and identifies peak rate periods.
        """
        accumulation_windows = {}
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            desc = period.get('shortForecast', '').lower()
            detailed = period.get('detailedForecast', '').lower()
            
            # Check if snow is happening
            has_snow = 'snow' in desc or 'snow' in detailed
            if not has_snow:
                continue
            
            # Estimate accumulation (rough: extract from detailed forecast if possible)
            # NWS doesn't always provide accumulation, so infer from description
            accumulation = self._estimate_accumulation(detailed)
            
            # Group by 3-hour window
            window_key = (dt.hour // 3) * 3
            if window_key not in accumulation_windows:
                accumulation_windows[window_key] = 0
            accumulation_windows[window_key] += accumulation
        
        return accumulation_windows
    
    def _estimate_accumulation(self, forecast_text: str) -> float:
        """Estimate snowfall accumulation from text description."""
        # Look for specific amounts first
        if 'trace' in forecast_text:
            return 0.1
        if '1 to 2' in forecast_text or '1-2' in forecast_text:
            return 1.5
        if '2 to 4' in forecast_text or '2-4' in forecast_text:
            return 3.0
        if '3 to 6' in forecast_text or '3-6' in forecast_text:
            return 4.5
        if '6 to 8' in forecast_text or '6-8' in forecast_text:
            return 7.0
        if '8 to 12' in forecast_text or '8-12' in forecast_text:
            return 10.0
        if '12 to 16' in forecast_text or '12-16' in forecast_text:
            return 14.0
        
        # Generic snow language fallback
        if 'heavy snow' in forecast_text or 'significant snow' in forecast_text:
            return 0.5
        if 'snow' in forecast_text:
            return 0.25
        
        return 0.0
    
    def analyze_early_morning_timing(self, day_hours: List[Dict]) -> float:
        """
        Heavy emphasis on snow falling during critical morning hours (4am-8am).
        This is THE most important factor for school closure decisions.
        """
        score = 0.0
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            hour = dt.hour
            desc = period.get('shortForecast', '').lower()
            detailed = period.get('detailedForecast', '').lower()
            
            has_snow = 'snow' in desc or 'snow' in detailed
            if not has_snow:
                continue
            
            # Critical window: 4am-8am (peak impact on morning commute)
            if 4 <= hour <= 8:
                accumulation = self._estimate_accumulation(detailed)
                # High weight: even small amounts matter here
                if accumulation >= 3:
                    score += 40
                elif accumulation >= 1:
                    score += 25
                else:
                    score += 10
            
            # Secondary window: 2am-4am (still impacts early commute)
            elif 2 <= hour < 4:
                accumulation = self._estimate_accumulation(detailed)
                if accumulation >= 2:
                    score += 20
                elif accumulation >= 1:
                    score += 12
            
            # Late night (10pm-2am): accumulates but less critical
            elif 22 <= hour or hour <= 2:
                accumulation = self._estimate_accumulation(detailed)
                if accumulation >= 4:
                    score += 8
        
        return score
    
    def analyze_total_accumulation(self, day_hours: List[Dict]) -> float:
        """Score based on total daily snowfall amount."""
        total_accumulation = 0.0
        
        for period in day_hours:
            detailed = period.get('detailedForecast', '').lower()
            total_accumulation += self._estimate_accumulation(detailed)
        
        score = 0.0
        
        # Thresholds based on typical closure criteria
        if total_accumulation >= 12:
            score += 35
        elif total_accumulation >= 8:
            score += 28
        elif total_accumulation >= 6:
            score += 20
        elif total_accumulation >= 4:
            score += 12
        elif total_accumulation >= 2:
            score += 5
        
        return score
    
    def analyze_road_conditions(self, day_hours: List[Dict]) -> float:
        """
        Score based on temperature and visibility affecting road safety.
        Roads with cold temps stay snow-covered; warm temps allow melting/treatment.
        """
        score = 0.0
        temps = []
        visibilities = []
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            
            # Focus on daytime hours when roads matter most
            if 6 <= dt.hour <= 18:
                temps.append(period['temperature'])
                vis_str = period.get('visibility', '')
                vis_val = self._extract_number(vis_str)
                if vis_val:
                    visibilities.append(vis_val)
        
        if not temps:
            return 0.0
        
        avg_temp = sum(temps) / len(temps)
        min_temp = min(temps)
        
        # Very cold temps (roads won't treat/clear effectively)
        if avg_temp < 15:
            score += 15
        elif avg_temp < 25:
            score += 8
        elif avg_temp < 32:
            score += 4
        
        # Freeze risk (below 32)
        if min_temp < 32:
            score += 5
        
        # Poor visibility
        if visibilities:
            min_vis = min(visibilities)
            if min_vis < 0.5:
                score += 12
            elif min_vis < 1.0:
                score += 6
        
        return score
    
    def analyze_hazardous_precip(self, day_hours: List[Dict]) -> float:
        """Score for freezing rain, sleet, and ice - these guarantee closures."""
        score = 0.0
        
        for period in day_hours:
            desc = period.get('shortForecast', '').lower()
            detailed = period.get('detailedForecast', '').lower()
            
            if 'freezing rain' in detailed or 'freezing rain' in desc:
                score += 50  # Nearly always causes closure
            elif 'ice storm' in detailed:
                score += 45
            elif 'sleet' in detailed or 'ice pellets' in detailed:
                score += 30
            elif 'freezing drizzle' in detailed:
                score += 20
        
        return score
    
    def analyze_alerts(self) -> float:
        """Score based on active weather alerts."""
        score = 0.0
        if not self.alerts:
            return 0.0
        
        for alert in self.alerts:
            event = alert['properties'].get('event', '')
            if 'Blizzard Warning' in event:
                score += 50
            elif 'Ice Storm Warning' in event:
                score += 48
            elif 'Winter Storm Warning' in event:
                score += 35
            elif 'Wind Chill Warning' in event:
                score += 15
            elif 'Winter Weather Advisory' in event:
                score += 18
            elif 'Wind Chill Advisory' in event:
                score += 8
        
        return min(score, 50.0)
    
    def analyze_wind_impact(self, day_hours: List[Dict]) -> float:
        """Score based on wind affecting visibility and wind chill."""
        score = 0.0
        high_wind_hours = 0
        
        for period in day_hours:
            wind_speed = period.get('windSpeed')
            
            if wind_speed:
                speed_val = self._extract_number(wind_speed)
                if speed_val and speed_val > 25:
                    high_wind_hours += 1
        
        if high_wind_hours >= 6:
            score += 15
        elif high_wind_hours >= 3:
            score += 8
        
        return score
    
    @staticmethod
    def _extract_number(s: str) -> Optional[float]:
        """Extract numeric value from strings like '10 mph' or '5 mi'."""
        try:
            return float(''.join(c for c in s.split()[0] if c.isdigit() or c == '.'))
        except (ValueError, IndexError):
            return None

    # -------------------------
    # Main calculation
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
            weekday_num = day_date.weekday()
            
            if day_date <= today or weekday_num >= 5:
                continue
            
            day_hours = periods_by_date[day_date]
            
            # Prioritize timing and accumulation
            early_morning_score = self.analyze_early_morning_timing(day_hours)
            accumulation_score = self.analyze_total_accumulation(day_hours)
            hazard_precip_score = self.analyze_hazardous_precip(day_hours)
            road_score = self.analyze_road_conditions(day_hours)
            alerts_score = self.analyze_alerts()
            wind_score = self.analyze_wind_impact(day_hours)
            
            # Weighted total - timing and accumulation dominate
            total_score = (
                (early_morning_score * 2.0) +  # Double weight on critical timing
                (accumulation_score * 1.5) +   # Heavy weight on total snow
                (hazard_precip_score * 1.8) +  # High weight on ice/freezing rain
                (road_score * 1.0) +
                alerts_score +
                wind_score
            )
            
            # More conservative probability function
            # Calibrated so ~80 points = 50% probability
            # Max theoretical: (40*2) + (35*1.5) + (50*1.8) + (15) + (50) + (15) = ~250
            probability = (100 / (1 + (2.7183 ** (-0.03 * (total_score - 80)))))
            probability = max(1, min(99, int(probability)))
            
            # Likelihood label
            if probability < 10:
                likelihood = "VERY UNLIKELY"
            elif probability < 25:
                likelihood = "UNLIKELY"
            elif probability < 50:
                likelihood = "POSSIBLE"
            elif probability < 70:
                likelihood = "LIKELY"
            else:
                likelihood = "VERY LIKELY"
            
            results.append({
                'date': day_date.strftime('%Y-%m-%d'),
                'weekday': day_date.strftime('%A'),
                'probability': probability,
                'likelihood': likelihood,
                'score_breakdown': {
                    'early_morning_timing': round(early_morning_score, 1),
                    'total_accumulation': round(accumulation_score, 1),
                    'hazardous_precip': round(hazard_precip_score, 1),
                    'road_conditions': round(road_score, 1),
                    'alerts': round(alerts_score, 1),
                    'wind': round(wind_score, 1),
                    'total': round(total_score, 1)
                },
                'note': 'This is an estimate. Always check official school district announcements.'
            })
            
            counted_days += 1
            if counted_days >= 4:
                break
        
        return {
            'success': True,
            'location': self.location_name,
            'zipcode': self.zipcode,
            'probabilities': results,
            'timestamp': datetime.now().strftime('%Y-%m-%d %I:%M %p'),
            'disclaimer': 'This calculator provides estimates based on weather data. School closure decisions are made by district superintendents considering multiple factors including road conditions, equipment availability, and county coordination. Always rely on official district announcements.'
        }


def get_snow_day_probabilities(zipcode: str) -> Dict:
    """Convenience function to get snow day probabilities."""
    calculator = ImprovedSnowDayCalculator(zipcode)
    return calculator.calculate_next_weekday_probabilities()