def analyze_cold_with_snow(self, day_hours: List[Dict], min_bus_chill: float, total_snow: float) -> Tuple[float, str]:
        """Score extreme cold COMBINED with snow/road issues. Triggers earlier than cold alone."""
        score = 0.0
        factor_type = "cold_with_snow"
        
        # COLD + SNOW combined: lower threshold, higher impact
        if min_bus_chill <= -15 and total_snow >= 1.0:
            score = 75
        elif min_bus_chill <= -10 and total_snow >= 2.0:
            score = 60
        elif min_bus_chill <= -5 and total_snow >= 3.0:
            score = 50
        elif min_bus_chill <= 0 and total_snow >= 4.0:
            score = 45
        
        return score, factor_typeimport requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re
import math

class ImprovedSnowDayCalculator:
    """
    Production-grade Snow Day Calculator using NWS Gridpoint Data.
    Calibrated for Michigan schools based on actual closure patterns.
    """
    
    DISTRICT_PROFILES = {
        'michigan': {
            'accumulation_threshold': 3.0,
            'timing_weight': 2.0,
            'name': 'Michigan Schools'
        },
        'conservative': {
            'accumulation_threshold': 2.5,
            'timing_weight': 2.5,
            'name': 'Conservative (closes early)'
        },
        'tough': {
            'accumulation_threshold': 5.0,
            'timing_weight': 1.5,
            'name': 'Tough (tolerates more)'
        }
    }
    
    def __init__(self, zipcode: str, district_profile: str = 'michigan'):
        self.zipcode = zipcode
        self.district_profile = district_profile
        self.profile_name = self.DISTRICT_PROFILES.get(district_profile, {}).get('name', 'Michigan')
        self.profile = self.DISTRICT_PROFILES.get(district_profile, self.DISTRICT_PROFILES['michigan'])
        
        self.lat = None
        self.lon = None
        self.location_name = None
        self.base_url = "https://api.weather.gov"
        self.headers = {
            'User-Agent': '(SnowDayCalculator, github.com)',
            'Accept': 'application/json'
        }
        self.hourly_forecast = None
        self.alerts = None
        self.error_message = None

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

    def _extract_number(self, s: Optional[str]) -> Optional[float]:
        """Extract numeric value from formatted strings."""
        if not s:
            return None
        try:
            match = re.search(r'(\d+(?:\.\d+)?)', str(s))
            if match:
                return float(match.group(1))
        except (ValueError, AttributeError):
            pass
        return None
    
    def _extract_precipitation_data(self, period: Dict) -> Tuple[Optional[float], Optional[int]]:
        """Extract QPF (liquid equivalent, inches) and probability."""
        try:
            qpf_amount = None
            if 'quantitativePrecipitation' in period and period['quantitativePrecipitation']:
                precip_val = period['quantitativePrecipitation'].get('value')
                if precip_val is not None:
                    qpf_amount = precip_val / 25.4
            
            precip_prob = None
            if 'precipitationProbability' in period and period['precipitationProbability']:
                precip_prob = period['precipitationProbability'].get('value')
            
            return qpf_amount, precip_prob
        except Exception:
            return None, None
    
    def _is_snow_period(self, period: Dict) -> bool:
        """Determine if period contains snow/wintry precip."""
        desc = period.get('shortForecast', '').lower()
        detailed = period.get('detailedForecast', '').lower()
        icon = period.get('icon', '').lower()
        
        snow_keywords = ['snow', 'blizzard', 'sleet', 'freezing rain', 'ice', 'wintry']
        combined_text = f"{desc} {detailed} {icon}"
        
        return any(keyword in combined_text for keyword in snow_keywords)
    
    def _qpf_to_snow_depth(self, qpf_inches: float, period_temp: float) -> float:
        """Convert QPF to snow depth using period-specific temperature."""
        if qpf_inches <= 0:
            return 0.0
        
        if period_temp > 30:
            ratio = 8.0
        elif period_temp > 25:
            ratio = 9.5
        elif period_temp > 20:
            ratio = 10.0
        elif period_temp > 15:
            ratio = 12.0
        else:
            ratio = 15.0
        
        return qpf_inches * ratio
    
    def _extract_visibility(self, period: Dict) -> Optional[float]:
        """Extract visibility in miles."""
        vis = period.get('visibility')
        if vis:
            val = self._extract_number(vis)
            if val:
                return val
        return None
    
    def _extract_wind_speed(self, period: Dict) -> Optional[float]:
        """Extract wind speed in mph."""
        wind = period.get('windSpeed')
        if wind:
            val = self._extract_number(wind)
            if val:
                return val
        return None
    
    def _get_temperature_fahrenheit(self, period: Dict) -> Optional[float]:
        """Extract temperature in Fahrenheit with safe fallback."""
        temp = period.get('temperature')
        if temp is None:
            return None
        
        unit_code = period.get('temperatureUnit', 'F')
        
        if unit_code == 'C' or unit_code == 'wmoUnit:degC':
            return (temp * 9/5) + 32
        
        return float(temp) if temp is not None else None
    
    def _extract_wind_chill(self, period: Dict) -> Optional[float]:
        """Extract or calculate wind chill for a period."""
        temp = self._get_temperature_fahrenheit(period)
        wind_speed = self._extract_wind_speed(period)
        
        if temp is None or wind_speed is None:
            return None
        
        if temp > 50 or wind_speed <= 3:
            return temp
        
        v_power = math.pow(wind_speed, 0.16)
        wind_chill = 35.74 + (0.6215 * temp) - (35.75 * v_power) + (0.4275 * temp * v_power)
        
        return wind_chill
    
    def _get_forecast_age(self, day_hours: List[Dict]) -> int:
        """Estimate forecast age in hours."""
        if not day_hours:
            return 72
        
        first_period = day_hours[0]
        start_time = first_period.get('startTime')
        if not start_time:
            return 72
        
        try:
            dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            
            hours_ahead = max(0, int((dt - now).total_seconds() / 3600))
            return hours_ahead
        except (ValueError, AttributeError):
            return 72

    def _compute_min_bus_chill(self, day_hours: List[Dict]) -> float:
        """Compute minimum wind chill during extended bus window (6:30am-4:00pm)."""
        bus_hour_chills = []
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            
            # Check if time is within 6:30am to 4:00pm (16:00)
            if (dt.hour == 6 and dt.minute >= 30) or (6 < dt.hour < 16) or (dt.hour == 16 and dt.minute == 0):
                chill = self._extract_wind_chill(period)
                if chill is not None:
                    bus_hour_chills.append(chill)
        
        return min(bus_hour_chills) if bus_hour_chills else 32.0
    
    def analyze_extreme_cold(self, day_hours: List[Dict], min_bus_chill: float) -> Tuple[float, str]:
        """Score extreme cold ALONE. -19 to -22°F is closure threshold for cold only."""
        score = 0.0
        factor_type = "cold_only"
        
        # COLD ALONE scoring (-19 to -22°F range is hard closure)
        if min_bus_chill <= -22:
            score = 95
        elif min_bus_chill <= -21:
            score = 92
        elif min_bus_chill <= -20:
            score = 88
        elif min_bus_chill <= -19:
            score = 85
        elif min_bus_chill <= -15:
            score = 50
        elif min_bus_chill <= -10:
            score = 30
        
        return score, factor_type
    
    def analyze_early_morning_timing(self, day_hours: List[Dict]) -> Tuple[float, Dict]:
        """Snow during critical 4-6am bus commute window - highest weight."""
        score = 0.0
        details = {
            'critical_window_snow_depth': 0.0,
            'peak_probability': 0.0,
            'continuous_hours': 0,
        }
        
        critical_window_snow = 0.0
        peak_commute_snow = 0.0  # 4-6am is MOST critical
        
        for period in day_hours:
            start_time = period.get('startTime')
            if not start_time:
                continue
            
            try:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                continue
            
            hour = dt.hour
            
            if not self._is_snow_period(period):
                continue
            
            qpf_amount, precip_prob = self._extract_precipitation_data(period)
            if qpf_amount is None or qpf_amount <= 0:
                continue
            
            period_temp = period.get('temperature', 32)
            snow_depth = self._qpf_to_snow_depth(qpf_amount, period_temp)
            
            # PEAK COMMUTE: 4-6am gets HIGHEST multiplier (2.5x)
            if 4 <= hour < 6:
                peak_commute_snow += snow_depth
                
                if snow_depth >= 0.4:
                    score += 50 * 2.5  # Triple weight for peak hours
                elif snow_depth >= 0.2:
                    score += 35 * 2.5
                elif snow_depth >= 0.1:
                    score += 20 * 2.5
                else:
                    score += 10 * 2.5
                
                if precip_prob and precip_prob > details['peak_probability']:
                    details['peak_probability'] = precip_prob
            
            # EARLY COMMUTE: 6-8am (1.5x weight)
            elif 6 <= hour <= 8:
                critical_window_snow += snow_depth
                
                if snow_depth >= 0.4:
                    score += 30 * 1.5
                elif snow_depth >= 0.15:
                    score += 18 * 1.5
                else:
                    score += 8 * 1.5
            
            # PRE-COMMUTE: 3-4am (1x weight) - road prep time
            elif 3 <= hour < 4:
                if snow_depth >= 0.3:
                    score += 15
                elif snow_depth > 0:
                    score += 8
        
        # Bonus for continuous snow during peak hours
        continuous_hours = self._count_continuous_snow_hours(day_hours, 4, 6)
        if continuous_hours >= 2:
            score += 40
        
        details['critical_window_snow_depth'] = round(peak_commute_snow, 2)
        details['continuous_hours'] = continuous_hours
        
        return score * self.profile['timing_weight'], details
    
    def _count_continuous_snow_hours(self, day_hours: List[Dict], start_hour: int, end_hour: int) -> float:
        """Count consecutive hours of snow in a window."""
        consecutive = 0
        max_consecutive = 0
        
        for period in day_hours:
            start_time = period.get('startTime')
            if not start_time:
                consecutive = 0
                continue
            
            try:
                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                consecutive = 0
                continue
            
            if start_hour <= dt.hour <= end_hour and self._is_snow_period(period):
                qpf, _ = self._extract_precipitation_data(period)
                if qpf and qpf > 0:
                    consecutive += 1
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0
            else:
                consecutive = 0
        
        return max_consecutive
    
    def analyze_total_accumulation(self, day_hours: List[Dict]) -> Tuple[float, float]:
        """Total snow depth - Michigan threshold discussion starts at 3-4 inches."""
        total_snow = 0.0
        
        for period in day_hours:
            if not self._is_snow_period(period):
                continue
            
            qpf_amount, _ = self._extract_precipitation_data(period)
            if qpf_amount and qpf_amount > 0:
                period_temp = period.get('temperature', 32)
                snow_depth = self._qpf_to_snow_depth(qpf_amount, period_temp)
                total_snow += snow_depth
        
        score = 0.0
        
        # Refined thresholds based on Michigan closure patterns
        if total_snow >= 6.0:
            score = 50
        elif total_snow >= 5.0:
            score = 45
        elif total_snow >= 4.5:
            score = 42
        elif total_snow >= 4.0:
            score = 38
        elif total_snow >= 3.5:
            score = 28
        elif total_snow >= 3.0:
            score = 20
        elif total_snow >= 2.0:
            score = 12
        elif total_snow >= 1.0:
            score = 6
        
        return score, total_snow
    
    def analyze_refreeze_risk(self, day_hours: List[Dict]) -> Tuple[float, bool]:
        """Detect icy roads from refreeze."""
        score = 0.0
        has_refreeze_risk = False
        
        last_snow_hour = None
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            
            if self._is_snow_period(period):
                qpf, _ = self._extract_precipitation_data(period)
                if qpf and qpf > 0:
                    last_snow_hour = dt.hour
        
        if last_snow_hour is None:
            return 0.0, False
        
        if last_snow_hour <= 4:
            temps_after = []
            for period in day_hours:
                dt = datetime.fromisoformat(period['startTime'])
                if 4 <= dt.hour <= 10:
                    temps_after.append(period.get('temperature', 32))
            
            if temps_after:
                min_temp = min(temps_after)
                if min_temp < 20:
                    score += 20
                    has_refreeze_risk = True
                elif min_temp < 28:
                    score += 12
                    has_refreeze_risk = True
        
        return score, has_refreeze_risk
    
    def analyze_road_conditions(self, day_hours: List[Dict]) -> float:
        """Road safety - PRIMARY factor for closure decisions per Michigan sources."""
        score = 0.0
        temps = []
        visibilities = []
        has_snow = False
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            
            # Focus on critical morning hours: 4am-10am
            if 4 <= dt.hour <= 10:
                temps.append(period.get('temperature', 32))
                
                if self._is_snow_period(period):
                    has_snow = True
                
                vis = self._extract_visibility(period)
                if vis:
                    visibilities.append(vis)
        
        if not temps:
            return 0.0
        
        avg_temp = sum(temps) / len(temps)
        min_temp = min(temps)
        
        # Road condition scoring - MAJOR FACTOR
        if avg_temp < 15:
            score += 35  # Very cold roads
        elif avg_temp < 25:
            score += 25  # Cold roads, hard to clear
        elif avg_temp < 32:
            score += 15  # Near freezing, slick potential
        
        if min_temp < 20:
            score += 20
        
        # ACTIVE SNOW = WORST ROAD CONDITIONS
        if has_snow:
            score += 30  # Snow actively falling during morning
            
            if visibilities:
                min_vis = min(visibilities)
                if min_vis < 0.25:
                    score += 40  # Near whiteout conditions
                elif min_vis < 0.5:
                    score += 30  # Heavy snow, poor visibility
                elif min_vis < 1.0:
                    score += 20  # Moderate snow impact
        
        return min(score, 100.0)
    
    def analyze_drifting_risk(self, day_hours: List[Dict]) -> float:
        """Wind + snow = drifting."""
        score = 0.0
        
        has_recent_snow = False
        last_snow_hour = None
        
        for period in day_hours:
            if self._is_snow_period(period):
                qpf, _ = self._extract_precipitation_data(period)
                if qpf and qpf > 0:
                    has_recent_snow = True
                    dt = datetime.fromisoformat(period['startTime'])
                    last_snow_hour = dt.hour
        
        if not has_recent_snow:
            return 0.0
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            wind = self._extract_wind_speed(period)
            
            if wind and wind > 25:
                if self._is_snow_period(period):
                    score += 12
                elif last_snow_hour and 0 <= (dt.hour - last_snow_hour) <= 6:
                    score += 8
        
        return min(score, 20.0)
    
    def analyze_hazardous_precip(self, day_hours: List[Dict]) -> float:
        """Freezing rain, sleet, ice - MAJOR independent closure triggers."""
        score = 0.0
        
        for period in day_hours:
            desc = period.get('shortForecast', '').lower()
            detailed = period.get('detailedForecast', '').lower()
            combined = f"{desc} {detailed}"
            
            if 'freezing rain' in combined:
                score += 70  # Increased from 50
            elif 'ice storm' in combined:
                score += 75  # Increased from 48
            elif 'sleet' in combined or 'ice pellets' in combined:
                score += 60  # Increased from 35
            elif 'freezing drizzle' in combined:
                score += 35  # Increased from 20
        
        return min(score, 75.0)
    
    def analyze_alerts(self, day_hours: List[Dict]) -> Tuple[Optional[str], float]:
        """Apply alerts only during decision window (3am-10am)."""
        if not self.alerts:
            return None, 0.0
        
        highest_alert = None
        highest_score = 0.0
        
        for alert in self.alerts:
            event = alert['properties'].get('event', '')
            
            effective_str = alert['properties'].get('effective')
            expires_str = alert['properties'].get('expires')
            
            if effective_str and expires_str:
                try:
                    effective = datetime.fromisoformat(effective_str.replace('Z', '+00:00'))
                    expires = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                    
                    day_start = datetime.fromisoformat(day_hours[0]['startTime'])
                    decision_window_start = day_start.replace(hour=3, minute=0, second=0)
                    decision_window_end = day_start.replace(hour=10, minute=0, second=0)
                    
                    if not (expires < decision_window_start or effective > decision_window_end):
                        if 'Blizzard Warning' in event:
                            if highest_score < 50:
                                highest_alert = 'Blizzard Warning'
                                highest_score = 50.0
                        elif 'Ice Storm Warning' in event:
                            if highest_score < 48:
                                highest_alert = 'Ice Storm Warning'
                                highest_score = 48.0
                        elif 'Winter Storm Warning' in event:
                            if highest_score < 40:
                                highest_alert = 'Winter Storm Warning'
                                highest_score = 40.0
                        elif 'Winter Weather Advisory' in event:
                            if highest_score < 20:
                                highest_alert = 'Winter Weather Advisory'
                                highest_score = 20.0
                except ValueError:
                    pass
        
        return highest_alert, highest_score
    
    def _calculate_severity_score(self, day_hours: List[Dict]) -> Dict:
        """Calculate all severity components."""
        min_bus_chill = self._compute_min_bus_chill(day_hours)
        extreme_cold_score = self.analyze_extreme_cold(day_hours, min_bus_chill)
        early_morning_score, timing_details = self.analyze_early_morning_timing(day_hours)
        accumulation_score, total_snow = self.analyze_total_accumulation(day_hours)
        refreeze_score, has_refreeze = self.analyze_refreeze_risk(day_hours)
        hazard_score = self.analyze_hazardous_precip(day_hours)
        road_score = self.analyze_road_conditions(day_hours)
        drifting_score = self.analyze_drifting_risk(day_hours)
        alert_type, alert_score = self.analyze_alerts(day_hours)

        # Snow-related score
        snow_score = early_morning_score + accumulation_score

        # Combine snow + cold - boost snow contribution if both present
        if snow_score > 0 and extreme_cold_score > 0:
            combined_boost = snow_score * 0.5
            snow_score += combined_boost

        # Total base score: always include extreme cold, snow, and other hazards
        base_score = extreme_cold_score + snow_score + refreeze_score + hazard_score + road_score + drifting_score
        
        return {
            'base_score': round(base_score, 2),
            'alert_type': alert_type,
            'extreme_cold': round(extreme_cold_score, 2),
            'early_morning': round(early_morning_score, 2),
            'accumulation': round(accumulation_score, 2),
            'total_snow_inches': round(total_snow, 2),
            'refreeze_risk': round(refreeze_score, 2),
            'hazardous_precip': round(hazard_score, 2),
            'drifting_risk': round(drifting_score, 2),
            'min_bus_chill': round(min_bus_chill, 2),
            'road_conditions': round(road_score, 2),
            'timing_details': timing_details,
            'has_refreeze': has_refreeze,
        }
    
    def _severity_to_probability(self, severity_score: float, alert_type: Optional[str]) -> Tuple[float, float]:
        """Convert severity score to probability, smooth mapping without rounding."""
        if alert_type == 'Blizzard Warning':
            return 96.0, 0.95
        elif alert_type == 'Ice Storm Warning':
            return 93.0, 0.93
        elif alert_type == 'Winter Storm Warning':
            return 82.0, 0.88
        elif alert_type == 'Winter Weather Advisory':
            return 58.0, 0.75

        # Smooth probability curve based on severity score
        # Extreme cold (-21°F+) now triggers 95-98%
        if severity_score <= 0:
            probability = 2.0
            confidence = 0.95
        elif severity_score < 50:
            # Linear boost for cold/light snow: 60 + (score/2)
            probability = 60.0 + (severity_score / 2.0)
            confidence = 0.85
        elif severity_score < 95:
            # Linear for moderate to high: 70 + (score/3)
            probability = 70.0 + (severity_score / 3.0)
            confidence = 0.82 + (severity_score / 500.0)
        elif severity_score < 100:
            # High extreme cold zone (95-100 score) = 95-98%
            probability = 95.0 + ((severity_score - 95) * 0.6)
            confidence = 0.92
        else:
            # Extreme: cap at 99%
            probability = 99.0
            confidence = 0.95

        probability = max(0.0, min(99.0, probability))
        confidence = max(0.0, min(1.0, confidence))
        
        return probability, confidence
    
    def _generate_plain_english_reason(self, severity: Dict, probability: int) -> str:
        """Generate human-readable explanation."""
        reasons = []
        
        if severity['alert_type']:
            reasons.append(f"🚨 {severity['alert_type']} in effect")
        
        if severity['extreme_cold'] > 0:
            reasons.append(f"Extreme cold: {int(severity['min_bus_chill'])}°F wind chill")
        
        if severity['total_snow_inches'] >= 3.0:
            reasons.append(f"{severity['total_snow_inches']:.1f}\" of snow expected")
        
        if severity['timing_details']['critical_window_snow_depth'] > 0:
            reasons.append(f"{severity['timing_details']['critical_window_snow_depth']:.1f}\" during 5-9am commute")
        
        if severity['has_refreeze']:
            reasons.append("Icy roads from refreeze")
        
        if severity['hazardous_precip'] > 0:
            reasons.append("Freezing rain or ice")
        
        if severity['drifting_risk'] > 0:
            reasons.append("Wind-driven drifting")
        
        if not reasons:
            reasons.append("No significant winter weather")
        
        return " | ".join(reasons)
    
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
        
        periods_by_date = {}
        for period in self.hourly_forecast:
            dt = datetime.fromisoformat(period['startTime'])
            day_date = dt.date()
            if day_date not in periods_by_date:
                periods_by_date[day_date] = []
            periods_by_date[day_date].append(period)
        
        for day_date in sorted(periods_by_date.keys()):
            weekday_num = day_date.weekday()
            
            if day_date <= today or weekday_num >= 5:
                continue
            
            day_hours = periods_by_date[day_date]
            
            severity = self._calculate_severity_score(day_hours)
            probability, confidence = self._severity_to_probability(severity['base_score'], severity['alert_type'])
            forecast_age = self._get_forecast_age(day_hours)
            
            if forecast_age > 72:
                confidence *= 0.80
            elif forecast_age > 48:
                confidence *= 0.90
            
            confidence = max(0.5, confidence)
            
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
            
            reason = self._generate_plain_english_reason(severity, probability)
            
            results.append({
                'date': day_date.strftime('%Y-%m-%d'),
                'weekday': day_date.strftime('%A'),
                'probability': round(probability, 2),
                'likelihood': likelihood,
                'confidence': round(confidence, 2),
                'reason': reason,
                'score_breakdown': {
                    'pathway_used': severity['pathway_used'],
                    'cold_alone_score': severity['cold_alone_score'],
                    'snow_road_alone_score': round(severity['snow_road_alone_score'], 2),
                    'cold_snow_road_combined_score': severity['cold_snow_road_score'],
                    'early_morning_timing': severity['early_morning'],
                    'total_snow_inches': severity['total_snow_inches'],
                    'accumulation_score': severity['accumulation'],
                    'refreeze_risk': severity['refreeze_risk'],
                    'hazardous_precip': severity['hazardous_precip'],
                    'drifting_risk': severity['drifting_risk'],
                    'min_bus_hour_chill': severity['min_bus_chill'],
                    'road_conditions': severity['road_conditions'],
                    'alert': severity['alert_type'] or 'None',
                    'base_severity_score': round(severity['base_score'], 2),
                },
                'note': 'Michigan school closure estimate'
            })
            
            counted_days += 1
            if counted_days >= 4:
                break
        
        return {
            'success': True,
            'location': self.location_name,
            'zipcode': self.zipcode,
            'district_profile': self.profile_name,
            'probabilities': results,
            'timestamp': datetime.now().strftime('%Y-%m-%d %I:%M %p'),
        }


def get_snow_day_probabilities(zipcode: str, district_profile: str = 'michigan') -> Dict:
    """Get snow day probabilities for Michigan schools."""
    calculator = ImprovedSnowDayCalculator(zipcode, district_profile)
    return calculator.calculate_next_weekday_probabilities()