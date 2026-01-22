import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re
import math

class mainapp:
    
    DISTRICT_PROFILES = {
        'michigan': {
            'accumulation_threshold': 3.0,
            'timing_weight': 2.0,
            'cold_threshold': -18,  # Wind chill for cold closures (actual MI threshold)
            'name': 'Michigan Schools'
        },
        'conservative': {
            'accumulation_threshold': 2.5,
            'timing_weight': 2.5,
            'cold_threshold': -16,  # Closes earlier than typical
            'name': 'Conservative (closes early)'
        },
        'tough': {
            'accumulation_threshold': 5.0,
            'timing_weight': 1.5,
            'cold_threshold': -25,  # Rarely closes for cold
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
        try:
            qpf_amount = None
            if 'quantitativePrecipitation' in period and period['quantitativePrecipitation']:
                precip_val = period['quantitativePrecipitation'].get('value')
                if precip_val is not None:
                    qpf_amount = precip_val / 25.4
            
            precip_prob = None
            if 'probabilityOfPrecipitation' in period and period['probabilityOfPrecipitation']:
                precip_prob = period['probabilityOfPrecipitation'].get('value')
            
            return qpf_amount, precip_prob
        except Exception:
            return None, None
    
    def _is_snow_period(self, period: Dict) -> bool:
        desc = period.get('shortForecast', '').lower()
        detailed = period.get('detailedForecast', '').lower()
        icon = period.get('icon', '').lower()
        
        snow_keywords = ['snow', 'blizzard', 'sleet', 'freezing rain', 'ice', 'wintry']
        combined_text = f"{desc} {detailed} {icon}"
        
        return any(keyword in combined_text for keyword in snow_keywords)
    
    def _qpf_to_snow_depth(self, qpf_inches: float, period_temp: float) -> float:
        if qpf_inches <= 0:
            return 0.0
        
        # Improved snow ratio based on temperature
        if period_temp > 32:
            ratio = 5.0  # Wet, heavy snow
        elif period_temp > 28:
            ratio = 8.0
        elif period_temp > 25:
            ratio = 10.0
        elif period_temp > 20:
            ratio = 12.0
        elif period_temp > 15:
            ratio = 15.0
        elif period_temp > 10:
            ratio = 18.0
        else:
            ratio = 20.0  # Very light, fluffy snow
        
        return qpf_inches * ratio
    
    def _extract_visibility(self, period: Dict) -> Optional[float]:
        vis = period.get('visibility')
        if vis:
            val = self._extract_number(vis.get('value') if isinstance(vis, dict) else vis)
            if val:
                # Convert meters to miles if needed
                if isinstance(vis, dict) and vis.get('unitCode') == 'wmoUnit:m':
                    return val * 0.000621371
                return val
        return None
    
    def _extract_wind_speed(self, period: Dict) -> Optional[float]:
        wind = period.get('windSpeed')
        if wind:
            val = self._extract_number(wind)
            if val:
                return val
        return None
    
    def _get_temperature_fahrenheit(self, period: Dict) -> Optional[float]:
        temp = period.get('temperature')
        if temp is None:
            return None
        
        unit_code = period.get('temperatureUnit', 'F')
        
        if unit_code == 'C' or unit_code == 'wmoUnit:degC':
            return (temp * 9/5) + 32
        
        return float(temp) if temp is not None else None
    
    def _extract_wind_chill(self, period: Dict) -> Optional[float]:
        temp = self._get_temperature_fahrenheit(period)
        wind_speed = self._extract_wind_speed(period)
        
        if temp is None or wind_speed is None:
            return None
        
        if temp > 50 or wind_speed <= 3:
            return temp
        
        # Official NWS wind chill formula
        v_power = math.pow(wind_speed, 0.16)
        wind_chill = 35.74 + (0.6215 * temp) - (35.75 * v_power) + (0.4275 * temp * v_power)
        
        return wind_chill
    
    def _get_forecast_age(self, day_hours: List[Dict]) -> int:
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
        bus_hour_chills = []
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            
            # Morning bus time (6-9am) and afternoon (2-4pm)
            if 4 <= dt.hour < 10:
                chill = self._extract_wind_chill(period)
                if chill is not None:
                    bus_hour_chills.append(chill)
        
        return min(bus_hour_chills) if bus_hour_chills else 32.0
    
    def analyze_extreme_cold(self, day_hours: List[Dict], min_bus_chill: float) -> Tuple[float, str]:
        score = 0.0
        factor_type = "cold_only"
        
        # Calibrated to actual Michigan closure patterns
        if min_bus_chill <= -30:
            score = 85  # Virtually certain closure
        elif min_bus_chill <= -25:
            score = 75  # Very high probability
        elif min_bus_chill <= -22:
            score = 65  # High probability (many districts close)
        elif min_bus_chill <= -19:
            score = 50  # Moderate-high (threshold for most districts)
        elif min_bus_chill <= -16:
            score = 25  # Some districts may close
        elif min_bus_chill <= -13:
            score = 10  # Unlikely, only most conservative districts
        else:
            score = 0
        
        return score, factor_type
    
    def analyze_early_morning_timing(self, day_hours: List[Dict]) -> Tuple[float, Dict]:
        score = 0.0
        details = {
            'critical_window_snow_depth': 0.0,
            'peak_probability': 0.0,
            'continuous_hours': 0,
        }
        
        critical_window_snow = 0.0
        
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
            
            # 5am-8am: Most critical for road conditions
            if 5 <= hour < 8:
                critical_window_snow += snow_depth
                
                # Much more conservative scoring
                if snow_depth >= 1.0:  # 1"+ per hour is significant
                    score += 40
                elif snow_depth >= 0.5:
                    score += 25
                elif snow_depth >= 0.3:
                    score += 12
                elif snow_depth >= 0.15:
                    score += 5
                
                if precip_prob and precip_prob > details['peak_probability']:
                    details['peak_probability'] = precip_prob
            
            # 8am-10am: Still important but roads being treated
            elif 8 <= hour < 10:
                if snow_depth >= 0.8:
                    score += 20
                elif snow_depth >= 0.4:
                    score += 10
                elif snow_depth >= 0.2:
                    score += 4
            
            # 4am-5am: Pre-positioning time
            elif 4 <= hour < 5:
                if snow_depth >= 0.5:
                    score += 8
                elif snow_depth >= 0.2:
                    score += 3
        
        # Bonus for sustained snow
        continuous_hours = self._count_continuous_snow_hours(day_hours, 5, 8)
        if continuous_hours >= 3:
            score += 25
        elif continuous_hours >= 2:
            score += 12
        
        details['critical_window_snow_depth'] = round(critical_window_snow, 2)
        details['continuous_hours'] = continuous_hours
        
        # Apply district timing weight
        return score * self.profile['timing_weight'], details
    
    def _count_continuous_snow_hours(self, day_hours: List[Dict], start_hour: int, end_hour: int) -> float:
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
            
            if start_hour <= dt.hour < end_hour and self._is_snow_period(period):
                qpf, _ = self._extract_precipitation_data(period)
                if qpf and qpf > 0.02:  # At least trace precipitation
                    consecutive += 1
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0
            elif dt.hour >= end_hour:
                break
            else:
                consecutive = 0
        
        return max_consecutive
    
    def analyze_total_accumulation(self, day_hours: List[Dict]) -> Tuple[float, float]:
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
        
        # Much more conservative - reflects that accumulation alone rarely closes schools
        if total_snow >= 12.0:
            score = 50  # Major snowstorm
        elif total_snow >= 10.0:
            score = 42
        elif total_snow >= 8.0:
            score = 35
        elif total_snow >= 6.0:
            score = 28
        elif total_snow >= 5.0:
            score = 22
        elif total_snow >= 4.0:
            score = 16
        elif total_snow >= 3.0:
            score = 10
        elif total_snow >= 2.0:
            score = 4
        elif total_snow >= 1.0:
            score = 1
        
        return score, total_snow
    
    def analyze_refreeze_risk(self, day_hours: List[Dict]) -> Tuple[float, bool]:
        score = 0.0
        has_refreeze_risk = False
        last_snow_hour = None
        snow_ended_recently = False
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            
            if self._is_snow_period(period):
                qpf, _ = self._extract_precipitation_data(period)
                if qpf and qpf > 0:
                    last_snow_hour = dt.hour
        
        if last_snow_hour is None:
            return 0.0, False
        
        # Check if snow ends in evening/night and refreezes for morning
        if last_snow_hour <= 6:  # Snow ended before or during early morning
            temps_after = []
            for period in day_hours:
                dt = datetime.fromisoformat(period['startTime'])
                if 4 <= dt.hour <= 10:
                    temp = period.get('temperature')
                    if temp is not None:
                        temps_after.append(temp)
            
            if temps_after:
                min_temp = min(temps_after)
                avg_temp = sum(temps_after) / len(temps_after)
                
                # Dangerous refreeze: well below freezing during commute
                if min_temp < 15:
                    score += 30
                    has_refreeze_risk = True
                elif min_temp < 20:
                    score += 20
                    has_refreeze_risk = True
                elif min_temp < 25 and avg_temp < 28:
                    score += 10
                    has_refreeze_risk = True
        
        return score, has_refreeze_risk
    
    def analyze_road_conditions(self, day_hours: List[Dict]) -> float:
        score = 0.0
        morning_temps = []
        visibilities = []
        has_snow = False
        has_ice = False
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            
            # Focus on morning commute hours
            if 5 <= dt.hour <= 9:
                temp = period.get('temperature')
                if temp is not None:
                    morning_temps.append(temp)
                
                desc = period.get('shortForecast', '').lower()
                if 'ice' in desc or 'freezing' in desc:
                    has_ice = True
                
                if self._is_snow_period(period):
                    has_snow = True
                
                vis = self._extract_visibility(period)
                if vis:
                    visibilities.append(vis)
        
        if not morning_temps:
            return 0.0
        
        avg_temp = sum(morning_temps) / len(morning_temps)
        min_temp = min(morning_temps)
        
        # Ice is a major factor
        if has_ice:
            score += 40
        
        # Temperature impact on road treatment effectiveness
        if avg_temp < 10:
            score += 20  # Salt doesn't work well
        elif avg_temp < 20:
            score += 12
        elif avg_temp < 25:
            score += 6
        
        # Snow during commute
        if has_snow:
            score += 15
            
            # Visibility matters significantly with snow
            if visibilities:
                min_vis = min(visibilities)
                if min_vis < 0.25:
                    score += 30  # Near-zero visibility
                elif min_vis < 0.5:
                    score += 20
                elif min_vis < 1.0:
                    score += 12
                elif min_vis < 2.0:
                    score += 6
        
        return min(score, 70.0)
    
    def analyze_drifting_risk(self, day_hours: List[Dict]) -> float:
        score = 0.0
        has_recent_snow = False
        last_snow_hour = None
        total_recent_snow = 0.0
        
        for period in day_hours:
            if self._is_snow_period(period):
                qpf, _ = self._extract_precipitation_data(period)
                if qpf and qpf > 0:
                    has_recent_snow = True
                    dt = datetime.fromisoformat(period['startTime'])
                    last_snow_hour = dt.hour
                    period_temp = period.get('temperature', 32)
                    total_recent_snow += self._qpf_to_snow_depth(qpf, period_temp)
        
        if not has_recent_snow:
            return 0.0
        
        # Check wind conditions during/after snow
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            wind = self._extract_wind_speed(period)
            
            if wind and wind > 15:
                # Active snow with wind
                if self._is_snow_period(period):
                    if wind > 30:
                        score += 15
                    elif wind > 25:
                        score += 10
                    elif wind > 20:
                        score += 6
                
                # Recent snow with strong wind (within 12 hours)
                elif last_snow_hour and 0 <= (dt.hour - last_snow_hour) <= 12:
                    if wind > 30 and total_recent_snow >= 3.0:
                        score += 12
                    elif wind > 25 and total_recent_snow >= 2.0:
                        score += 8
                    elif wind > 20:
                        score += 4
        
        return min(score, 25.0)
    
    def analyze_hazardous_precip(self, day_hours: List[Dict]) -> float:
        score = 0.0
        
        for period in day_hours:
            dt = datetime.fromisoformat(period['startTime'])
            
            # Only count during decision-relevant times
            if not (3 <= dt.hour <= 10):
                continue
            
            desc = period.get('shortForecast', '').lower()
            detailed = period.get('detailedForecast', '').lower()
            combined = f"{desc} {detailed}"
            
            # Ice is extremely serious
            if 'ice storm' in combined:
                score = 90  # Near-certain closure
                break
            elif 'freezing rain' in combined:
                qpf, _ = self._extract_precipitation_data(period)
                if qpf and qpf > 0.1:
                    score = max(score, 80)
                else:
                    score = max(score, 60)
            elif 'sleet' in combined or 'ice pellets' in combined:
                score = max(score, 50)
            elif 'freezing drizzle' in combined:
                score = max(score, 30)
        
        return score
    
    def analyze_alerts(self, day_hours: List[Dict]) -> Tuple[Optional[str], float]:
    
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
                
                    if effective < decision_window_end and expires > decision_window_start:
                    # Adjusted scores - alerts don't guarantee closures
                        if 'Blizzard Warning' in event:
                            if highest_score < 60:
                                highest_alert = 'Blizzard Warning'
                                highest_score = 60.0
                        elif 'Ice Storm Warning' in event:
                            if highest_score < 65:
                                highest_alert = 'Ice Storm Warning'
                                highest_score = 65.0
                        elif 'Winter Storm Warning' in event:
                            if highest_score < 45:
                                highest_alert = 'Winter Storm Warning'
                                highest_score = 45.0
                        elif 'Winter Weather Advisory' in event:
                            if highest_score < 15:
                                highest_alert = 'Winter Weather Advisory'
                                highest_score = 15.0
                        elif 'Wind Chill Warning' in event:
                            if highest_score < 35:
                                highest_alert = 'Wind Chill Warning'
                                highest_score = 35.0
                        elif 'Wind Chill Advisory' in event:
                            if highest_score < 12:
                                highest_alert = 'Wind Chill Advisory'
                                highest_score = 12.0
                except ValueError:
                    pass
        return highest_alert, highest_score
        
                    
    
    def _calculate_severity_score(self, day_hours: List[Dict]) -> Dict:
        min_bus_chill = self._compute_min_bus_chill(day_hours)
        extreme_cold_score, _ = self.analyze_extreme_cold(day_hours, min_bus_chill)
        early_morning_score, timing_details = self.analyze_early_morning_timing(day_hours)
        accumulation_score, total_snow = self.analyze_total_accumulation(day_hours)
        refreeze_score, has_refreeze = self.analyze_refreeze_risk(day_hours)
        hazard_score = self.analyze_hazardous_precip(day_hours)
        road_score = self.analyze_road_conditions(day_hours)
        drifting_score = self.analyze_drifting_risk(day_hours)
        alert_type, alert_score = self.analyze_alerts(day_hours)

        # Combine snow-related scores
        snow_score = early_morning_score + accumulation_score

        # IMPROVED: Snow + cold compound effect (more realistic)
        if snow_score > 20 and extreme_cold_score > 15:
            # Moderate boost for combined factors
            combined_boost = min(snow_score * 0.3, 25)
            snow_score += combined_boost

        # Calculate base score
        base_score = (
            extreme_cold_score +
            snow_score +
            refreeze_score +
            hazard_score +
            road_score +
            drifting_score +
            alert_score
        )
        
        return {
            'base_score': round(base_score, 2),
            'alert_type': alert_type,
            'alert_score': round(alert_score, 2),
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
        
        # Alert-based probabilities (still strong indicators but not guarantees)
        if alert_type == 'Blizzard Warning':
            return 75.0, 0.90
        elif alert_type == 'Ice Storm Warning':
            return 85.0, 0.92
        elif alert_type == 'Winter Storm Warning':
            return 55.0, 0.80
        elif alert_type == 'Wind Chill Warning':
            return 50.0, 0.78
        elif alert_type == 'Winter Weather Advisory':
            return 25.0, 0.70
        elif alert_type == 'Wind Chill Advisory':
            return 15.0, 0.65

        # MUCH MORE CONSERVATIVE score-to-probability mapping
        # Schools rarely close unless severity > 60-70
        if severity_score <= 0:
            probability = 1.0
            confidence = 0.85
        elif severity_score < 10:
            probability = 2.0
            confidence = 0.80
        elif severity_score < 20:
            probability = 5.0
            confidence = 0.75
        elif severity_score < 30:
            probability = 8.0
            confidence = 0.72
        elif severity_score < 40:
            probability = 12.0
            confidence = 0.70
        elif severity_score < 50:
            probability = 18.0
            confidence = 0.72
        elif severity_score < 60:
            probability = 28.0
            confidence = 0.75
        elif severity_score < 70:
            probability = 40.0
            confidence = 0.78
        elif severity_score < 80:
            probability = 55.0
            confidence = 0.82
        elif severity_score < 90:
            probability = 68.0
            confidence = 0.85
        elif severity_score < 100:
            probability = 78.0
            confidence = 0.88
        elif severity_score < 120:
            probability = 85.0
            confidence = 0.90
        else:
            probability = 92.0
            confidence = 0.92

        probability = max(0.0, min(95.0, probability))
        confidence = max(0.5, min(0.95, confidence))
        
        return probability, confidence
    
    def _generate_plain_english_reason(self, severity: Dict, probability: float) -> str:
        reasons = []
        
        if severity['alert_type']:
            reasons.append(f"🚨 {severity['alert_type']}")
        
        if severity['hazardous_precip'] > 40:
            reasons.append("⚠️ Freezing rain/ice expected")
        
        if severity['extreme_cold'] > 30:
            reasons.append(f"🥶 Dangerous cold: {int(severity['min_bus_chill'])}°F wind chill")
        elif severity['extreme_cold'] > 15:
            reasons.append(f"❄️ Very cold: {int(severity['min_bus_chill'])}°F wind chill")
        
        if severity['total_snow_inches'] >= 6.0:
            reasons.append(f"🌨️ {severity['total_snow_inches']:.1f}\" heavy snow")
        elif severity['total_snow_inches'] >= 3.0:
            reasons.append(f"🌨️ {severity['total_snow_inches']:.1f}\" snow expected")
        
        if severity['timing_details']['critical_window_snow_depth'] > 1.0:
            reasons.append(f"⏰ {severity['timing_details']['critical_window_snow_depth']:.1f}\" during morning commute")
        
        if severity['road_conditions'] > 30:
            reasons.append("🚗 Poor road conditions")
        
        if severity['has_refreeze']:
            reasons.append("🧊 Icy road risk")
        
        if severity['drifting_risk'] > 15:
            reasons.append("💨 Blowing/drifting snow")
        
        if not reasons:
            reasons.append("✅ No significant winter weather")
        
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
            
            # Skip weekends and past days
            if day_date <= today or weekday_num >= 5:
                continue
            
            day_hours = periods_by_date[day_date]
            severity = self._calculate_severity_score(day_hours)
            probability, confidence = self._severity_to_probability(severity['base_score'], severity['alert_type'])
            forecast_age = self._get_forecast_age(day_hours)
            
            # Adjust confidence based on forecast age
            if forecast_age > 96:
                confidence *= 0.70
            elif forecast_age > 72:
                confidence *= 0.80
            elif forecast_age > 48:
                confidence *= 0.90
            
            confidence = max(0.50, min(0.95, confidence))
            
            # Likelihood categories
            if probability < 5:
                likelihood = "VERY UNLIKELY"
            elif probability < 15:
                likelihood = "UNLIKELY"
            elif probability < 35:
                likelihood = "LOW CHANCE"
            elif probability < 55:
                likelihood = "POSSIBLE"
            elif probability < 70:
                likelihood = "LIKELY"
            elif probability < 85:
                likelihood = "VERY LIKELY"
            else:
                likelihood = "HIGHLY LIKELY"
            
            reason = self._generate_plain_english_reason(severity, probability)
            
            results.append({
                'date': day_date.strftime('%Y-%m-%d'),
                'weekday': day_date.strftime('%A'),
                'probability': round(probability, 1),
                'likelihood': likelihood,
                'confidence': round(confidence, 2),
                'reason': reason,
                'forecast_hours_ahead': forecast_age,
                'severity_breakdown': {
                    'total_severity_score': severity['base_score'],
                    'alert': severity['alert_type'] or 'None',
                    'alert_contribution': severity['alert_score'],
                    'extreme_cold_contribution': severity['extreme_cold'],
                    'min_bus_chill_f': severity['min_bus_chill'],
                    'timing_contribution': severity['early_morning'],
                    'accumulation_contribution': severity['accumulation'],
                    'total_snow_inches': severity['total_snow_inches'],
                    'critical_window_snow': severity['timing_details']['critical_window_snow_depth'],
                    'road_conditions_contribution': severity['road_conditions'],
                    'refreeze_contribution': severity['refreeze_risk'],
                    'hazardous_precip_contribution': severity['hazardous_precip'],
                    'drifting_contribution': severity['drifting_risk'],
                },
                'notes': [
                    f"Based on {self.profile_name} closure patterns",
                    f"Forecast issued {forecast_age}hrs ahead - accuracy varies"
                ]
            })
            
            counted_days += 1
            if counted_days >= 4:
                break
        
        return {
            'success': True,
            'location': self.location_name,
            'district_profile': self.profile_name,
            'probabilities': results,
            'disclaimer': "Probabilities are estimates based on weather conditions and historical patterns. Actual closure decisions depend on local road conditions and district policies."
        }


# Example usage
if __name__ == "__main__":
    # Test with a Michigan ZIP code
    calculator = mainapp("48374", district_profile='michigan')
    results = calculator.calculate_next_weekday_probabilities()
    
    if results['success']:
        print(f"\n{'='*80}")
        print(f"SNOW DAY FORECAST - {results['location']}")
        print(f"District Profile: {results['district_profile']}")
        print(f"{'='*80}\n")
        
        for day in results['probabilities']:
            print(f"\n{day['weekday']}, {day['date']}")
            print(f"  Probability: {day['probability']}% ({day['likelihood']})")
            print(f"  Confidence: {day['confidence']*100:.0f}%")
            print(f"  {day['reason']}")
            print(f"\n  Severity Breakdown (Total: {day['severity_breakdown']['total_severity_score']})")
            print(f"    • Alert: {day['severity_breakdown']['alert']} (+{day['severity_breakdown']['alert_contribution']})")
            print(f"    • Cold: {day['severity_breakdown']['min_bus_chill_f']:.0f}°F (+{day['severity_breakdown']['extreme_cold_contribution']})")
            print(f"    • Snow Total: {day['severity_breakdown']['total_snow_inches']:.1f}\" (+{day['severity_breakdown']['accumulation_contribution']})")
            print(f"    • Timing: {day['severity_breakdown']['critical_window_snow']:.1f}\" during commute (+{day['severity_breakdown']['timing_contribution']})")
            print(f"    • Road Conditions: +{day['severity_breakdown']['road_conditions_contribution']}")
            print(f"    • Ice/Refreeze: +{day['severity_breakdown']['refreeze_contribution']}")
            print(f"    • Hazardous Precip: +{day['severity_breakdown']['hazardous_precip_contribution']}")
            print(f"    • Drifting: +{day['severity_breakdown']['drifting_contribution']}")
            print(f"\n  Note: {day['notes'][1]}")
        
        print(f"\n{'='*80}")
        print(results['disclaimer'])
        print(f"{'='*80}\n")
    else:
        print(f"Error: {results['error']}")