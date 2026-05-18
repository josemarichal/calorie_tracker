import os
import sys
import re
import sqlite3
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
# from kivy.uix.button import Button # Not directly used in this snippet, but keep if used elsewhere
from kivy.uix.label import Label
# from kivy.uix.scrollview import ScrollView # Not directly used in this snippet
from kivy.lang import Builder
from kivy.clock import Clock
from datetime import date, timedelta, datetime # Keep 'date' for date objects
# import pandas as pd # REMOVED PANDAS
from kivy.utils import platform
from kivy.logger import Logger
from kivy.metrics import dp
from kivy.uix.screenmanager import ScreenManager, Screen
# from kivy.uix.gridlayout import GridLayout # Not directly used in this snippet
# from kivy.uix.textinput import TextInput # Not directly used in this snippet
from kivy.properties import ObjectProperty

# Flag to track if we can access the required storage
STORAGE_ACCESS_OK = True # Assume OK initially, set to False on error
DB_FILE = None # Will be set in App.on_start

def get_database_path():
    """Gets the appropriate database path for the platform."""
    global STORAGE_ACCESS_OK
    db_dir_to_use = None

    if platform == 'android':
        try:
            # from android.storage import app_storage_path # Not strictly needed if user_data_dir works
            context = App.get_running_app()
            if context and hasattr(context, 'user_data_dir') and context.user_data_dir:
                db_dir_to_use = context.user_data_dir
                Logger.info(f"Using Android Internal Storage (user_data_dir): {db_dir_to_use}")
            else:
                 # Fallback: this might be less reliable or need more setup on some Kivy versions
                 from android.storage import app_storage_path
                 app_path = app_storage_path()
                 if app_path:
                    db_dir_to_use = os.path.join(app_path, context.name if context else "app") # Ensure a subdirectory
                    Logger.info(f"Using Android Internal Storage (app_storage_path fallback): {db_dir_to_use}")
                 else:
                    Logger.error("Android: Could not retrieve user_data_dir or app_storage_path.")
                    STORAGE_ACCESS_OK = False
                    return None
        except ImportError:
             Logger.error("Android: Could not import android.storage. Ensure pyjnius is installed for app_storage_path if user_data_dir fails.")
             STORAGE_ACCESS_OK = False
             return None
        except Exception as e:
            Logger.error(f"Android: Error getting internal data path: {e}")
            STORAGE_ACCESS_OK = False
            return None
    else: # Desktop or other platforms
        try:
            # On desktop, create a subdirectory in the script's folder for cleaner organization
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_dir_to_use = os.path.join(script_dir, "app_data") # Store DB in an 'app_data' subfolder
            Logger.info(f"Using Desktop path: {db_dir_to_use}")
        except Exception as e:
            Logger.error(f"Desktop: Error determining app data path: {e}")
            STORAGE_ACCESS_OK = False
            return None


    if db_dir_to_use:
        try:
            if not os.path.exists(db_dir_to_use):
                os.makedirs(db_dir_to_use)
                Logger.info(f"Created directory: {db_dir_to_use}")
        except OSError as e: # Catch specific OS errors like permission denied
            Logger.error(f"Failed to create directory {db_dir_to_use} (OSError): {e}")
            STORAGE_ACCESS_OK = False
            return None
        except Exception as e: # Catch any other unexpected errors
            Logger.error(f"Failed to create directory {db_dir_to_use} (Exception): {e}")
            STORAGE_ACCESS_OK = False
            return None

        if not os.access(db_dir_to_use, os.W_OK | os.X_OK): # Check for write and execute (needed to create files in dir)
            Logger.error(f"Directory is not writable/accessible: {db_dir_to_use}")
            STORAGE_ACCESS_OK = False
            return None

        db_path = os.path.join(db_dir_to_use, "calorie_data.db")
        Logger.info(f"Database Path Set To: {db_path}")
        return db_path
    else:
        Logger.error("Could not determine a valid directory for the database.")
        STORAGE_ACCESS_OK = False
        return None

def init_db():
    """Initialize the SQLite database. Assumes DB_FILE is set."""
    global DB_FILE, STORAGE_ACCESS_OK

    if not STORAGE_ACCESS_OK or not DB_FILE:
        Logger.error("init_db: Cannot initialize, storage access issue or DB_FILE not set.")
        return False
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # Added 'id' for easier referencing if needed later, Date is still unique for data logic
        cursor.execute('''CREATE TABLE IF NOT EXISTS calorie_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Date TEXT UNIQUE NOT NULL, Weight REAL,
            Meal1 INTEGER, Meal2 INTEGER, Meal3 INTEGER,
            Meal4 INTEGER, Meal5 INTEGER, Meal6 INTEGER, TotalCalories INTEGER)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS temp_inputs (
            date TEXT PRIMARY KEY, weight TEXT, meal1 TEXT, meal2 TEXT,
            meal3 TEXT, meal4 TEXT, meal5 TEXT, meal6 TEXT)''')
        # Safe migration for Meal6
        try:
            cursor.execute("ALTER TABLE calorie_data ADD COLUMN Meal6 INTEGER")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        try:
            cursor.execute("ALTER TABLE temp_inputs ADD COLUMN meal6 TEXT")
        except sqlite3.OperationalError:
            pass # Column already exists
            
        conn.commit()
        conn.close()
        Logger.info(f"Database initialized/verified successfully at {DB_FILE}")
        return True
    except sqlite3.OperationalError as e: # Catch specific DB operational errors
        Logger.error(f"Database OperationalError (check path/permissions for {DB_FILE}): {e}")
        STORAGE_ACCESS_OK = False
        return False
    except Exception as e:
        Logger.exception(f"General database initialization error at {DB_FILE}: {e}")
        STORAGE_ACCESS_OK = False
        return False

class CalorieTracker(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._data_loaded_once = False
        self.data = [] # CHANGED: Now a list, not a DataFrame
        self.stats_cache = {
            'wc7': "N/A", 'wc14': "N/A", 'wc30': "N/A",
            'ac7': "N/A", 'ac14': "N/A", 'ac30': "N/A"
        }
        # Data loading is triggered by App after DB setup.
        # Binding inputs happens after load_data_and_ui completes successfully.

    def check_storage_and_load(self):
        """Called by App class after DB path is set and potentially initialized."""
        global STORAGE_ACCESS_OK
        if not STORAGE_ACCESS_OK:
            Logger.error("CalorieTracker: Cannot load data, storage access issue.")
            if hasattr(self, 'ids') and self.ids and 'status_label' in self.ids: # Defensive self.ids check
                self.ids.status_label.text = "Storage Error - Cannot Load Data"
                self.ids.status_label.color = (1, 0, 0, 1)
            return
        self.load_data_and_ui()

    def load_data_and_ui(self):
        global DB_FILE, STORAGE_ACCESS_OK
        if not STORAGE_ACCESS_OK or not DB_FILE:
            Logger.error("load_data_and_ui: Aborted due to storage issue or missing DB_FILE.")
            if hasattr(self, 'ids') and self.ids and 'status_label' in self.ids:
                self.ids.status_label.text = "Storage Error"
                self.ids.status_label.color = (1, 0, 0, 1)
            return

        try:
            self.load_data()
            self.calculate_summary_stats()

            current_date_str = datetime.now().strftime("%Y-%m-%d")

            if not hasattr(self, 'ids') or not self.ids:
                 Logger.error("load_data_and_ui: CRITICAL - self.ids dictionary not available.")
                 if hasattr(self, 'ids') and self.ids and 'status_label' in self.ids:
                    self.ids.status_label.text = "UI Init Error!"
                    self.ids.status_label.color = (1, 0, 0, 1)
                 return

            if 'date_input' in self.ids:
                self.ids.date_input.text = current_date_str
                self.load_temp_data(current_date_str)
                self.update_total_calories()
            else:
                 Logger.warning("load_data_and_ui: 'date_input' ID not found.")

            self._data_loaded_once = True

            if 'status_label' in self.ids:
                self.ids.status_label.text = "Ready"
                self.ids.status_label.color = (0.3, 0.3, 0.3, 1)
            else:
                Logger.warning("load_data_and_ui: 'status_label' ID not found.")

            self._bind_inputs()
            Logger.info("load_data_and_ui: Successfully completed and bound inputs.")

        except Exception as e:
            Logger.exception(f"!!! ERROR DURING load_data_and_ui !!!")
            import traceback
            tb_str = traceback.format_exc()
            error_line_snippet = "Unknown location"
            try:
                relevant_lines = [line for line in tb_str.strip().split('\n') if 'main.py' in line]
                if relevant_lines: error_line_snippet = relevant_lines[-1].strip()[:70]
                elif len(tb_str.strip().split('\n')) >=3: error_line_snippet = tb_str.strip().split('\n')[-3].strip()[:70]
            except IndexError: pass
            detailed_error_msg = f"Load Error: {type(e).__name__} near: {error_line_snippet}"
            if hasattr(self, 'ids') and self.ids and 'status_label' in self.ids:
                self.ids.status_label.text = detailed_error_msg
                self.ids.status_label.color = (1, 0, 0, 1)
            else: Logger.error("load_data_and_ui: 'status_label' not available to display error.")
            STORAGE_ACCESS_OK = False

    def _initialize_empty_data(self):
        """Helper to set self.data to an empty list."""
        Logger.info("Initializing self.data as an empty list.")
        self.data = []

    def load_data(self):
        """Load data from SQLite into a list of dictionaries."""
        if not self._ensure_db_access("Load Data"):
            self._initialize_empty_data()
            return

        self._initialize_empty_data() # Start with an empty list

        try:
            if not os.path.exists(DB_FILE):
                Logger.warning(f"Database file {DB_FILE} does not exist. Data remains empty.")
                if not init_db(): Logger.error("load_data: Failed to initialize DB schema when file was missing.")
                return

            conn = sqlite3.connect(DB_FILE)
            # Use row_factory to get rows as dictionary-like objects
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Select specific columns to ensure order and content
            cursor.execute("SELECT Date, Weight, Meal1, Meal2, Meal3, Meal4, Meal5, Meal6, TotalCalories FROM calorie_data ORDER BY Date ASC")
            rows = cursor.fetchall()
            conn.close()

            temp_data_list = []
            for row in rows:
                try:
                    # Convert date string to datetime.date object
                    date_obj = datetime.strptime(row['Date'], "%Y-%m-%d").date()
                    
                    # Ensure numeric fields are numbers, default to 0 or None if problematic
                    weight = float(row['Weight']) if row['Weight'] is not None else None
                    meal1 = int(row['Meal1']) if row['Meal1'] is not None else 0
                    meal2 = int(row['Meal2']) if row['Meal2'] is not None else 0
                    meal3 = int(row['Meal3']) if row['Meal3'] is not None else 0
                    meal4 = int(row['Meal4']) if row['Meal4'] is not None else 0
                    meal5 = int(row['Meal5']) if row['Meal5'] is not None else 0
                    meal6 = int(row['Meal6']) if row['Meal6'] is not None else 0
                    total_calories = int(row['TotalCalories']) if row['TotalCalories'] is not None else 0
                    
                    temp_data_list.append({
                        'Date': date_obj,
                        'Weight': weight,
                        'Meal1': meal1, 'Meal2': meal2, 'Meal3': meal3,
                        'Meal4': meal4, 'Meal5': meal5, 'Meal6': meal6,
                        'TotalCalories': total_calories
                    })
                except (ValueError, TypeError) as conversion_error:
                    Logger.error(f"Error converting row data: {row} - {conversion_error}. Skipping row.")
            
            self.data = temp_data_list # Assign the processed list
            Logger.info(f"Loaded {len(self.data)} records into list of dicts.")

        except Exception as e:
            Logger.exception(f"Error loading data into list of dicts from {DB_FILE}: {e}")
            self._initialize_empty_data() # Fallback
            if hasattr(self, 'ids') and self.ids and 'status_label' in self.ids:
                self.ids.status_label.text = "DB Read Error"
                self.ids.status_label.color = (1,0,0,1)
            STORAGE_ACCESS_OK = False

    def calculate_summary_stats(self):
        """Calculate summary statistics from self.data (list of dicts)."""
        if not self.data: # Check if self.data list is empty
            Logger.info("calculate_summary_stats: No data available (self.data is empty).")
            self.stats_cache = {key: "N/A" for key in self.stats_cache}
            return

        # Ensure data is sorted by date (it should be from SQL, but good to be sure if ever modified in memory)
        # self.data.sort(key=lambda x: x['Date']) # Uncomment if in-memory modifications might unsort

        try:
            latest_entry_date = self.data[-1]['Date'] # Assumes data is sorted and not empty

            for period_days in [7, 14, 30]:
                start_period_date = latest_entry_date - timedelta(days=period_days -1)
                
                # Filter data for the current period
                period_entries = [
                    entry for entry in self.data 
                    if entry['Date'] >= start_period_date and entry['Date'] <= latest_entry_date
                ]

                # Calculate Average Calories
                calories_in_period = [
                    entry['TotalCalories'] for entry in period_entries 
                    if entry.get('TotalCalories') is not None # Use .get for safety
                ]
                if calories_in_period:
                    avg_cals = sum(calories_in_period) / len(calories_in_period)
                    self.stats_cache[f'ac{period_days}'] = f"{avg_cals:.0f}"
                else:
                    self.stats_cache[f'ac{period_days}'] = "N/A"

                # Calculate Weight Change
                weights_in_period = [
                    entry for entry in period_entries 
                    if entry.get('Weight') is not None # Use .get for safety
                ]
                
                if len(weights_in_period) >= 1: # Need at least current weight
                    # Find the latest weight (should be the last one in sorted weights_in_period)
                    current_w_entry = max(weights_in_period, key=lambda x: x['Date'])
                    current_w = current_w_entry['Weight']

                    if len(weights_in_period) >= 2:
                        # Find the earliest weight in the period
                        start_w_entry = min(weights_in_period, key=lambda x: x['Date'])
                        start_w = start_w_entry['Weight']
                        weight_change = current_w - start_w
                        self.stats_cache[f'wc{period_days}'] = f"{weight_change:+.1f} lbs"
                    elif len(weights_in_period) == 1 and current_w_entry['Date'] == latest_entry_date :
                        # Only one weight entry, and it's today's, so change is 0 for this period relative to itself
                        self.stats_cache[f'wc{period_days}'] = f"{0.0:+.1f} lbs"
                    else:
                        self.stats_cache[f'wc{period_days}'] = "N/A" # Not enough data for change
                else:
                    self.stats_cache[f'wc{period_days}'] = "N/A" # No weight data in period
            
            Logger.info(f"Summary stats calculated: {self.stats_cache}")

        except Exception as e:
            Logger.exception(f"Error calculating summary stats (non-Pandas): {e}")
            self.stats_cache = {key: "N/A" for key in self.stats_cache}


    # --- Other methods (save_temp_data_on_change, update_total_calories_on_change, _ensure_db_access,
    # --- load_temp_data, save_temp_data, on_date_change, update_total_calories, save_data,
    # --- clear_temp_data, clear_inputs) should largely remain the same as they interact with
    # --- UI elements or direct SQLite for `temp_inputs`, not heavily with `self.data`'s structure
    # --- for reading, except for `save_data` needing to call `load_data` and `calculate_summary_stats`.

    def _bind_inputs(self):
        if not hasattr(self, 'ids') or not self.ids or 'date_input' not in self.ids:
             Logger.warning("_bind_inputs: IDs not available yet or date_input missing.")
             return
        try:
            self.ids.date_input.unbind(text=self.on_date_change)
            self.ids.weight_input.unbind(text=self.save_temp_data_on_change)
            for i in range(1, 7):
                meal_id = f'meal{i}_input'
                if meal_id in self.ids:
                    self.ids[meal_id].unbind(text=self.save_temp_data_on_change)
                    self.ids[meal_id].unbind(text=self.update_total_calories_on_change)

            self.ids.date_input.bind(text=self.on_date_change)
            self.ids.weight_input.bind(text=self.save_temp_data_on_change)
            for i in range(1, 7):
                meal_id = f'meal{i}_input'
                if meal_id in self.ids:
                    self.ids[meal_id].bind(text=self.save_temp_data_on_change)
                    self.ids[meal_id].bind(text=self.update_total_calories_on_change)
            Logger.info("Input bindings set.")
        except Exception as e:
            Logger.exception(f"Error binding inputs: {e}")

    def save_temp_data_on_change(self, instance, value):
        if self._data_loaded_once and STORAGE_ACCESS_OK:
            self.save_temp_data()

    def update_total_calories_on_change(self, instance, value):
        if self._data_loaded_once:
            self.update_total_calories()

    def _ensure_db_access(self, operation_name="Operation"):
        if not STORAGE_ACCESS_OK or not DB_FILE:
            Logger.error(f"{operation_name}: Aborted due to storage/DB file issue.")
            if hasattr(self, 'ids') and self.ids and 'status_label' in self.ids:
                 self.ids.status_label.text = "Storage Error!"
                 self.ids.status_label.color = (1, 0, 0, 1)
            return False
        return True

    def load_temp_data(self, date_str):
        if not self._ensure_db_access("Load Temp Data"): return
        if not hasattr(self, 'ids') or not self.ids or 'weight_input' not in self.ids:
            Logger.warning("load_temp_data: IDs not ready, skipping.")
            return
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT weight, meal1, meal2, meal3, meal4, meal5, meal6 FROM temp_inputs WHERE date = ?", (date_str,))
            row = cursor.fetchone()
            conn.close()
            bindings = {}
            fields_to_set = {'weight_input': 0, 'meal1_input': 1, 'meal2_input': 2, 'meal3_input': 3, 'meal4_input': 4, 'meal5_input': 5, 'meal6_input': 6}
            for widget_id, idx in fields_to_set.items():
                if widget_id in self.ids:
                    widget = self.ids[widget_id]
                    bindings[widget_id] = []
                    observers = widget.get_property_observers('text')
                    if observers:
                        for observer in observers:
                             func_name = getattr(observer, '__name__', None)
                             if func_name == 'save_temp_data_on_change':
                                  bindings[widget_id].append(self.save_temp_data_on_change)
                                  widget.unbind(text=self.save_temp_data_on_change)
                             elif func_name == 'update_total_calories_on_change':
                                 bindings[widget_id].append(self.update_total_calories_on_change)
                                 widget.unbind(text=self.update_total_calories_on_change)
                    widget.text = row[idx] if row and row[idx] is not None else ''
            for widget_id, funcs in bindings.items():
                 widget = self.ids[widget_id]
                 for func in funcs: widget.bind(text=func)
            self.update_total_calories()
        except Exception as e:
            Logger.exception(f"Error loading temp data for {date_str}: {e}")
            STORAGE_ACCESS_OK = False

    def save_temp_data(self, *args):
        if not self._ensure_db_access("Save Temp Data"): return
        if not hasattr(self, 'ids') or not self.ids or 'date_input' not in self.ids:
             Logger.warning("save_temp_data: IDs not ready.")
             return
        try:
            current_date = self.ids.date_input.text.strip()
            if not current_date: return
            try: datetime.strptime(current_date, "%Y-%m-%d")
            except ValueError:
                Logger.warning(f"save_temp_data: Invalid date format '{current_date}', not saving.")
                return
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''INSERT OR REPLACE INTO temp_inputs VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                           (current_date, self.ids.weight_input.text, self.ids.meal1_input.text,
                            self.ids.meal2_input.text, self.ids.meal3_input.text,
                            self.ids.meal4_input.text, self.ids.meal5_input.text, self.ids.meal6_input.text))
            conn.commit()
            conn.close()
        except Exception as e:
            Logger.exception(f"Error saving temp data: {e}")
            STORAGE_ACCESS_OK = False

    def on_date_change(self, instance, value):
        if not self._data_loaded_once: return
        if not hasattr(self, 'ids') or not self.ids or 'status_label' not in self.ids:
            Logger.warning("on_date_change: status_label or IDs not ready.")
            return
        try:
            datetime.strptime(value, "%Y-%m-%d")
            self.ids.status_label.text = "Loading data for new date..."
            self.ids.status_label.color = (0.3, 0.3, 0.3, 1)
            self.load_temp_data(value)
        except ValueError:
            self.ids.status_label.text = "Invalid date format. Use YYYY-MM-DD."
            self.ids.status_label.color = (1, 0, 0, 1)
        except Exception as e:
            Logger.exception(f"Error on_date_change: {e}")
            self.ids.status_label.text = "Error changing date."
            self.ids.status_label.color = (1, 0, 0, 1)


    def update_total_calories(self, *args):
        """Calculate and update total calories display.
        Shows a numeric total only if all 6 meals are filled with valid numbers.
        """
        if not hasattr(self, 'ids') or not self.ids or 'total_calories_label' not in self.ids:
            return

        total_cal = 0
        all_six_meals_filled_numerically = True # Assume true initially
        
        for i in range(1, 7): # Check Meal 1 to Meal 5
            meal_input_id = f'meal{i}_input'
            meal_input = self.ids.get(meal_input_id)

            if not meal_input: # Should not happen
                all_six_meals_filled_numerically = False
                break 

            text_val = meal_input.text.strip()
            if not text_val: # If empty
                all_six_meals_filled_numerically = False
                break 
            
            if text_val.isdigit():
                total_cal += int(text_val)
            else: # Not empty, but not a digit
                all_six_meals_filled_numerically = False
                break 
        
        try:
            if all_six_meals_filled_numerically:
                self.ids.total_calories_label.text = str(total_cal)
                self.ids.total_calories_label.color = (0.1,0.4,0.75,1) # Normal color
            else:
                # Calculate partial sum for display if user wants to see it while filling,
                # but the label will indicate incompleteness.
                partial_sum = 0
                has_invalid_entry = False
                for i_partial in range(1, 7):
                    meal_input_partial = self.ids.get(f'meal{i_partial}_input')
                    if meal_input_partial:
                        text_val_partial = meal_input_partial.text.strip()
                        if text_val_partial.isdigit():
                            partial_sum += int(text_val_partial)
                        elif text_val_partial: # Filled but not a digit
                            has_invalid_entry = True
                
                if has_invalid_entry:
                    self.ids.total_calories_label.text = f"{partial_sum} (Invalid)"
                else:
                    self.ids.total_calories_label.text = f"{partial_sum} (Incomplete)"
                self.ids.total_calories_label.color = (0.5, 0.5, 0.5, 1) # Grayed out / placeholder color
        except Exception as e:
            Logger.exception(f"Error updating total calories display: {e}")
            if 'total_calories_label' in self.ids : self.ids.total_calories_label.text = "Err"

    def save_data(self):
        """Save data to the database, ensuring ALL FIVE meal fields are filled."""
        if not self._ensure_db_access("Save Data"): return
        if not (hasattr(self, 'ids') and self.ids and 'status_label' in self.ids):
            Logger.warning("Save Data: Status label or IDs not found.")
            return

        date_text = self.ids.date_input.text.strip()
        weight_text = self.ids.weight_input.text.strip()

        # --- Basic Validation: Date and Weight ---
        if not date_text or not weight_text:
            self.ids.status_label.text = "Date and Weight fields are required."
            self.ids.status_label.color = (1, 0.1, 0.1, 1)
            return
        try:
            formatted_date_str = datetime.strptime(date_text, "%Y-%m-%d").strftime("%Y-%m-%d")
            weight = float(weight_text)
        except ValueError:
            self.ids.status_label.text = "Invalid Date or Weight format."
            self.ids.status_label.color = (1, 0.1, 0.1, 1)
            return

        # --- Meal Input Validation (ALL SIX MEALS ARE NOW MANDATORY) ---
        parsed_meals_values = [] # To store integer values for DB
        current_total_calories = 0

        for i in range(1, 7): # Iterate through Meal 1 to Meal 5
            meal_id_str = f'meal{i}_input'
            meal_widget = self.ids.get(meal_id_str)

            if not meal_widget: # Should not happen if KV is correct
                Logger.error(f"Save Data: Missing meal widget ID: {meal_id_str}")
                self.ids.status_label.text = f"Internal Error: UI for Meal {i} missing."
                self.ids.status_label.color = (1,0.1,0.1,1)
                return

            val_str = meal_widget.text.strip()
            
            if not val_str: # Check if the meal input is empty
                self.ids.status_label.text = f"Meal {i} is required. All 6 meals must be filled."
                self.ids.status_label.color = (1, 0.1, 0.1, 1)
                return # Stop if any meal is empty
            
            if val_str.isdigit():
                val = int(val_str)
                parsed_meals_values.append(val)
                current_total_calories += val
            else: # Non-digit found in a meal input
                self.ids.status_label.text = f"Meal {i} must be a number."
                self.ids.status_label.color = (1, 0.1, 0.1, 1)
                return # Stop if any meal is not a valid number
        
        # At this point, all 6 meals are filled and are valid numbers.

        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''INSERT OR REPLACE INTO calorie_data
                            (Date, Weight, Meal1, Meal2, Meal3, Meal4, Meal5, Meal6, TotalCalories)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                           (formatted_date_str, weight, *parsed_meals_values, current_total_calories))
            conn.commit()
            conn.close()

            self.load_data()
            self.calculate_summary_stats()
            self.clear_temp_data(formatted_date_str)

            # Clear input fields
            self.ids.weight_input.text = ''
            for i_clear in range(1, 7):
                 meal_id_to_clear = f'meal{i_clear}_input'
                 if meal_id_to_clear in self.ids:
                    self.ids[meal_id_to_clear].text = ''
            
            self.update_total_calories() # Update display (will show "Incomplete" or 0 now)
            
            self.ids.status_label.text = "Data saved successfully!"
            self.ids.status_label.color = (0.1, 0.7, 0.2, 1)
            
            self.save_temp_data() # Save empty state for the current date

        except Exception as e:
            Logger.exception(f"Error saving data to DB: {e}")
            self.ids.status_label.text = f"Save error: {str(e)[:30]}"
            self.ids.status_label.color = (1, 0.1, 0.1, 1)
            STORAGE_ACCESS_OK = False

    def clear_temp_data(self, date_str):
        if not STORAGE_ACCESS_OK or not DB_FILE:
            Logger.warning(f"clear_temp_data: Skipped for {date_str} due to storage/DB issue")
            return
        try:
             if not date_str: return
             conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
             cursor.execute("DELETE FROM temp_inputs WHERE date = ?", (date_str,))
             conn.commit(); conn.close()
             Logger.info(f"Cleared temp data for {date_str}")
        except Exception as e:
             Logger.exception(f"Error clearing temp data for {date_str}: {e}")

    def clear_inputs(self):
        if not (hasattr(self, 'ids') and self.ids and 'date_input' in self.ids):
            Logger.warning("clear_inputs: IDs not ready."); return
        current_date = self.ids.date_input.text.strip()
        bindings = {}; fields_to_clear = ['weight_input'] + [f'meal{i}_input' for i in range(1, 7)]
        for widget_id in fields_to_clear:
             if widget_id in self.ids:
                 widget = self.ids[widget_id]; bindings[widget_id] = []
                 observers = widget.get_property_observers('text')
                 if observers:
                    for observer in observers:
                        func_name = getattr(observer, '__name__', None)
                        if func_name == 'save_temp_data_on_change':
                             bindings[widget_id].append(self.save_temp_data_on_change)
                             widget.unbind(text=self.save_temp_data_on_change)
                        elif func_name == 'update_total_calories_on_change':
                             bindings[widget_id].append(self.update_total_calories_on_change)
                             widget.unbind(text=self.update_total_calories_on_change)
                 widget.text = ''
        for widget_id, funcs in bindings.items():
             if widget_id in self.ids:
                 widget = self.ids[widget_id]
                 for func in funcs: widget.bind(text=func)
        self.update_total_calories()
        if current_date: self.clear_temp_data(current_date)
        self.save_temp_data() # Save the now-empty state
        if 'status_label' in self.ids:
            self.ids.status_label.text = 'Input fields cleared.'
            self.ids.status_label.color = (0.3,0.3,0.3,1)


class CalorieTrackerScreen(Screen):
    tracker_instance = ObjectProperty(None)

class ProgressScreen(Screen):
    def on_enter(self):
        app = App.get_running_app()
        if app and app.root and hasattr(app.root, 'get_screen'):
            try:
                tracker_screen = app.root.get_screen('calorie_tracker')
                if tracker_screen and tracker_screen.tracker_instance:
                    tracker_screen.tracker_instance.calculate_summary_stats()
            except Exception as e:
                 Logger.error(f"ProgressScreen: Error accessing tracker to recalculate stats: {e}")
        self.update_display()

    def update_display(self):
        stats = {}
        app = App.get_running_app()
        try:
            if app and app.root and hasattr(app.root, 'get_screen'):
                tracker_screen = app.root.get_screen('calorie_tracker')
                if tracker_screen and tracker_screen.tracker_instance:
                     stats = getattr(tracker_screen.tracker_instance, 'stats_cache', {})
        except Exception as e: Logger.error(f"ProgressScreen: Error retrieving stats cache: {e}")

        if not (hasattr(self, 'ids') and self.ids):
            Logger.warning("ProgressScreen.update_display: IDs not available.")
            self._set_all_stats_to_na_progress() # Try to set N/A even if some IDs are missing
            return

        if not stats: self._set_all_stats_to_na_progress(); return
        try:
            self.ids.ps_weight_change_7.text = stats.get('wc7', "N/A")
            self.ids.ps_weight_change_14.text = stats.get('wc14', "N/A")
            self.ids.ps_weight_change_30.text = stats.get('wc30', "N/A")
            self.ids.ps_avg_calories_7.text = stats.get('ac7', "N/A")
            self.ids.ps_avg_calories_14.text = stats.get('ac14', "N/A")
            self.ids.ps_avg_calories_30.text = stats.get('ac30', "N/A")
            self.apply_stat_coloring(self.ids.ps_weight_change_7)
            self.apply_stat_coloring(self.ids.ps_weight_change_14)
            self.apply_stat_coloring(self.ids.ps_weight_change_30)
        except KeyError as e:
            Logger.error(f"ProgressScreen: Missing ID in KV during update: {e}.")
            self._set_all_stats_to_na_progress()
        except Exception as e_gen:
            Logger.error(f"ProgressScreen: General error updating display: {e_gen}")
            self._set_all_stats_to_na_progress()

    def _set_all_stats_to_na_progress(self):
        default_color = (0.3, 0.3, 0.3, 1)
        if hasattr(self, 'ids') and self.ids: # Check if ids exist
            for period in [7, 14, 30]:
                for stat_type in ['weight_change', 'avg_calories']:
                    widget_id = f'ps_{stat_type}_{period}'
                    if widget_id in self.ids: # Check if specific id exists
                        self.ids[widget_id].text = "N/A"
                        self.ids[widget_id].color = default_color
                    else:
                        Logger.warning(f"ProgressScreen: Missing ID '{widget_id}' in _set_all_stats_to_na_progress.")
        else:
             Logger.warning("ProgressScreen: Cannot set N/A, self.ids not found.")

    def apply_stat_coloring(self, label_widget):
        default_color = (0.3,0.3,0.3,1); loss_color=(0.1,0.7,0.2,1); gain_color=(0.8,0.2,0.1,1)
        try:
            text_val = label_widget.text
            if "N/A" in text_val or not text_val.strip() or "lbs" not in text_val:
                label_widget.color = default_color; return
            numeric_part = text_val.replace("lbs", "").replace("+", "").strip()
            value = float(numeric_part)
            if value < 0: label_widget.color = loss_color
            elif value > 0: label_widget.color = gain_color
            else: label_widget.color = default_color
        except ValueError: Logger.warning(f"Could not parse value for coloring: {label_widget.text}"); label_widget.color = default_color
        except Exception as e: Logger.error(f"Error applying stat coloring: {e}"); label_widget.color = default_color

    def go_back(self, instance): self.manager.current = 'calorie_tracker'

class CalorieTrackerApp(App):
    def build(self):
        current_date_hint = datetime.now().strftime("%Y-%m-%d")
        # KV String remains the same
        kv_string_content = f"""

#:import dp kivy.metrics.dp

# --- Custom Widget Styles ---
<InputLabel@Label>:
    size_hint_x: 0.45
    font_size: '15sp'
    halign: 'left'
    valign: 'middle'
    text_size: self.width, None
    color: 0.2, 0.2, 0.2, 1

<ValueInput@TextInput>:
    multiline: False
    size_hint_x: 0.55
    font_size: '15sp'
    padding: [dp(8), dp(10)]
    hint_text_color: 0.6, 0.6, 0.6, 1

<ActionButton@Button>:
    font_size: '16sp'
    size_hint_y: None
    height: dp(48)
    color: 1, 1, 1, 1
    background_normal: ''
    background_down: '' # To make background_color effective

<StatHeader@Label>:
    bold: True
    font_size: '13sp'
    halign: 'center'
    valign: 'middle'
    text_size: self.width - dp(4), None
    padding_x: dp(2)
    
<StatValue@Label>:
    font_size: '13sp'
    halign: 'center'
    valign: 'middle'
    text_size: self.width - dp(4), None
    padding_x: dp(2)

# --- Screen Definitions ---
<CalorieTrackerScreen>:
    tracker_instance: tracker_content_id
    CalorieTracker:
        id: tracker_content_id

<ProgressScreen>:
    BoxLayout:
        orientation: 'vertical'
        padding: dp(15)
        spacing: dp(12)
        canvas.before:
            Color:
                rgba: 0.92, 0.92, 0.94, 1
            Rectangle:
                pos: self.pos
                size: self.size
        Label:
            text: 'Progress Report'
            font_size: '26sp'
            bold: True
            color: 0.15, 0.15, 0.2, 1
            size_hint_y: None
            height: self.texture_size[1] + dp(20)
        GridLayout:
            id: progress_stats_grid
            cols: 4
            size_hint_y: None
            height: self.minimum_height
            row_default_height: dp(40) 
            row_force_default: True    
            spacing: dp(5)
            padding: [0, dp(10), 0, dp(10)]

            StatHeader:
                text: 'Period'
                halign: 'left'
                size_hint_x: 0.30
                color: 0.1,0.1,0.1,1
            StatHeader:
                text: '7 Days'
                size_hint_x: 0.23
                color: 0.1,0.1,0.1,1
            StatHeader:
                text: '14 Days'
                size_hint_x: 0.23
                color: 0.1,0.1,0.1,1
            StatHeader:
                text: '30 Days'
                size_hint_x: 0.24
                color: 0.1,0.1,0.1,1

            StatValue:
                text: 'Wt Change:'
                halign: 'left'
                size_hint_x: 0.30
                color: 0.3,0.3,0.3,1
            StatValue:
                id: ps_weight_change_7
                text: 'N/A'
                size_hint_x: 0.23
            StatValue:
                id: ps_weight_change_14
                text: 'N/A'
                size_hint_x: 0.23
            StatValue:
                id: ps_weight_change_30
                text: 'N/A'
                size_hint_x: 0.24

            StatValue:
                text: 'Avg Cals:'
                halign: 'left'
                size_hint_x: 0.30
                color: 0.3,0.3,0.3,1
            StatValue:
                id: ps_avg_calories_7
                text: 'N/A'
                size_hint_x: 0.23
                color: 0.3,0.3,0.3,1
            StatValue:
                id: ps_avg_calories_14
                text: 'N/A'
                size_hint_x: 0.23
                color: 0.3,0.3,0.3,1
            StatValue:
                id: ps_avg_calories_30
                text: 'N/A'
                size_hint_x: 0.24
                color: 0.3,0.3,0.3,1
        BoxLayout: # Spacer
            size_hint_y: 1 
        ActionButton:
            text: 'Back to Tracker'
            on_press: root.go_back(self)
            background_color: 0.4,0.4,0.7,1
            # size_hint_y: None # Already in ActionButton rule
            # height: dp(48)   # Already in ActionButton rule
            
<CalorieTracker>:
    orientation: 'vertical'
    ScrollView:
        bar_width: dp(8)
        bar_color: 0.3,0.3,0.7,0.9
        effect_cls: "ScrollEffect" # Ensure this effect is valid or remove if unsure
        BoxLayout:
            orientation: 'vertical'
            padding: dp(15)
            spacing: dp(12)
            size_hint_y: None
            height: self.minimum_height
            canvas.before:
                Color:
                    rgba: 0.94,0.94,0.96,1
                Rectangle:
                    pos: self.pos
                    size: self.size
            BoxLayout: # Header Text Layout
                size_hint_y: None
                height: self.minimum_height # Make sure this is what you intend
                padding: [0, dp(10)]
                Label:
                    text: 'Daily Wellness Tracker'
                    font_size: '26sp'
                    bold: True
                    color: 0.15,0.15,0.2,1
                    halign: 'center'
                    size_hint_y: None
                    height: self.texture_size[1]
            BoxLayout: # Date and Weight Inputs
                orientation: 'vertical'
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(8)
                BoxLayout: # Date row
                    orientation: 'horizontal'
                    height: dp(42)
                    size_hint_y: None
                    InputLabel:
                        text: 'Date (YYYY-MM-DD):'
                    ValueInput:
                        id: date_input
                        hint_text: 'e.g., {current_date_hint}'
                BoxLayout: # Weight row
                    orientation: 'horizontal'
                    height: dp(42)
                    size_hint_y: None
                    InputLabel:
                        text: 'Weight (lbs):'
                    ValueInput:
                        id: weight_input
                        input_filter: 'float'
                        hint_text: 'e.g., 150.5'
            Label: # Meal Calories Section Title
                text: "Meal Calories"
                font_size: '18sp'
                bold: True
                size_hint_y: None
                height: self.texture_size[1] + dp(15)
                color: 0.25,0.25,0.3,1
                padding: [0, dp(5)]
            GridLayout: # Meal Inputs Grid
                cols: 2
                spacing: (dp(10),dp(8)) # Tuple for spacing (horizontal, vertical)
                row_default_height: dp(42)
                row_force_default: True
                size_hint_y: None
                height: self.minimum_height
                InputLabel:
                    text: 'Meal 1:'
                ValueInput:
                    id: meal1_input
                    input_filter: 'int'
                    hint_text: 'e.g., 500'
                InputLabel:
                    text: 'Meal 2:'
                ValueInput:
                    id: meal2_input
                    input_filter: 'int'
                    hint_text: 'e.g., 600'
                InputLabel:
                    text: 'Meal 3:'
                ValueInput:
                    id: meal3_input
                    input_filter: 'int'
                    hint_text: 'e.g., 700'
                InputLabel:
                    text: 'Meal 4 (Opt):' # Changed from (Optional) for brevity
                ValueInput:
                    id: meal4_input
                    input_filter: 'int'
                    hint_text: 'e.g., 200'
                InputLabel:
                    text: 'Meal 5 (Opt):' # Changed from (Optional) for brevity
                ValueInput:
                    id: meal5_input
                    input_filter: 'int'
                    hint_text: 'e.g., 150'
                InputLabel:
                    text: 'Meal 6 (Opt):'
                ValueInput:
                    id: meal6_input
                    input_filter: 'int'
                    hint_text: 'e.g., 100'
            BoxLayout: # Total Calories Display
                orientation: 'horizontal'
                size_hint_y: None
                height: dp(40)
                padding: [0, dp(8)]
                Label:
                    text: 'Total Calories Today:'
                    font_size: '16sp'
                    bold: True
                    color: 0.1,0.1,0.1,1
                    halign: 'right'
                    valign: 'middle'
                    text_size: self.width, None
                    size_hint_x: 0.65
                Label:
                    id: total_calories_label
                    text: '0'
                    font_size: '18sp'
                    bold: True
                    color: 0.1,0.4,0.75,1
                    halign: 'left'
                    valign: 'middle'
                    size_hint_x: 0.35
            BoxLayout: # Action Buttons (Save, Clear)
                orientation: 'horizontal'
                size_hint_y: None
                height: dp(48)
                spacing: dp(10)
                padding: [0, dp(15), 0, dp(10)] # Added top padding for consistency
                ActionButton:
                    text: 'Save Day'
                    on_press: root.save_data()
                    background_color: 0.25,0.65,0.35,1
                ActionButton:
                    text: 'Clear Fields'
                    on_press: root.clear_inputs()
                    background_color: 0.85,0.35,0.3,1
            BoxLayout: # Status Label
                size_hint_y: None
                height: dp(30)
                Label:
                    id: status_label
                    text: 'Initializing...'
                    halign: 'center'
                    font_size: '14sp'
                    color: 0.3,0.3,0.3,1
            BoxLayout: # View Full Progress Report Button
                size_hint_y: None
                height: dp(60) # Increased height slightly for better tap target
                padding: [0, dp(10), 0, dp(10)] # Symmetrical padding
                ActionButton:
                    text: 'View Full Progress Report'
                    on_press: app.root.current = 'progress'
                    background_color: 0.2,0.5,0.8,1
"""        
        
        try:
            Builder.load_string(kv_string_content)
        except Exception as e_kv:
            Logger.exception("CRITICAL: Error loading KV string!")
            return Label(text=f"KV Load Error:\n{e_kv}", halign='center', valign='middle')

        sm = ScreenManager()
        try:
            sm.add_widget(CalorieTrackerScreen(name='calorie_tracker'))
            sm.add_widget(ProgressScreen(name='progress'))
        except Exception as e_screen:
            Logger.exception("CRITICAL: Error creating/adding screens!")
            return Label(text=f"Screen Setup Error:\n{e_screen}", halign='center', valign='middle')
        return sm

    def on_start(self):
        global DB_FILE, STORAGE_ACCESS_OK
        Logger.info("App on_start: Determining database path...")
        DB_FILE = get_database_path()
        if not DB_FILE or not STORAGE_ACCESS_OK:
            Logger.error("App on_start: Failed to get valid DB path or storage access.")
            # Try to update UI status label if possible
            self._update_status_on_critical_error("CRITICAL: Storage Error!")
            return

        Logger.info("App on_start: Initializing database schema...")
        if not init_db():
            Logger.error("App on_start: Failed to initialize database schema.")
            self._update_status_on_critical_error("CRITICAL: DB Init Error!")
            # App might still run with in-memory data, or fail at DB operations
            # return # Optional: stop if DB init is absolutely critical for any operation

        Logger.info("App on_start: Triggering initial data load in CalorieTracker.")
        Clock.schedule_once(self.trigger_tracker_load, 0.3) # Initial delay

    def _update_status_on_critical_error(self, message):
        """Helper to update status label if app UI is partially built."""
        try:
            if self.root and hasattr(self.root, 'get_screen'):
                tracker_screen = self.root.get_screen('calorie_tracker')
                if tracker_screen and tracker_screen.tracker_instance and \
                   hasattr(tracker_screen.tracker_instance, 'ids') and \
                   tracker_screen.tracker_instance.ids and \
                   'status_label' in tracker_screen.tracker_instance.ids:
                    tracker_screen.tracker_instance.ids.status_label.text = message
                    tracker_screen.tracker_instance.ids.status_label.color = (1,0,0,1)
        except Exception as e:
            Logger.error(f"Error setting status label during critical error: {e}")


    def trigger_tracker_load(self, dt):
        try:
            if self.root and hasattr(self.root, 'get_screen'):
                tracker_screen = self.root.get_screen('calorie_tracker')
                if tracker_screen:
                    Logger.info(f"trigger_tracker_load: Found tracker_screen: {tracker_screen}")
                    tracker_instance = tracker_screen.tracker_instance
                    Logger.info(f"trigger_tracker_load: Checking tracker_instance: {tracker_instance}")
                    if tracker_instance:
                        Logger.info(f"trigger_tracker_load: tracker_instance type: {type(tracker_instance)}")
                        if hasattr(tracker_instance, 'ids') and tracker_instance.ids:
                            Logger.info(f"trigger_tracker_load: tracker_instance IDs are AVAILABLE. Proceeding with load.")
                            tracker_instance.check_storage_and_load()
                            # Trigger voice recognition after successful load
                            if platform == 'android':
                                Logger.info("trigger_tracker_load: Scheduling startup prompt.")
                                Clock.schedule_once(self.show_startup_prompt, 0.5)
                        else:
                            Logger.warning(f"trigger_tracker_load: tracker_instance IDs NOT YET available. Rescheduling (delay: {dt + 0.2:.2f}s).")
                            Clock.schedule_once(self.trigger_tracker_load, dt + 0.2)
                            return
                    else: Logger.error("trigger_tracker_load: CalorieTracker instance is None.")
                else: Logger.error("trigger_tracker_load: Could not get 'calorie_tracker' screen.")
            else: Logger.error("trigger_tracker_load: App root or screen manager not ready.")
        except Exception as e:
             Logger.exception(f"Error triggering tracker load: {e}")

    def show_startup_prompt(self, dt=0):
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.textinput import TextInput
        from kivy.uix.button import Button

        content = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(10))
        content.add_widget(Label(text='What were the calories for your next meal?', size_hint_y=None, height=dp(30)))
        
        self.popup_input = TextInput(input_filter='int', multiline=False, size_hint_y=None, height=dp(40), hint_text='e.g. 500')
        content.add_widget(self.popup_input)
        
        btn_layout = BoxLayout(orientation='horizontal', spacing=dp(10), size_hint_y=None, height=dp(40))
        submit_btn = Button(text='Save', background_color=(0.25,0.65,0.35,1))
        cancel_btn = Button(text='Cancel', background_color=(0.85,0.35,0.3,1))
        
        btn_layout.add_widget(submit_btn)
        btn_layout.add_widget(cancel_btn)
        content.add_widget(btn_layout)

        self.startup_popup = Popup(title='Next Meal Entry', content=content, size_hint=(0.8, 0.4), auto_dismiss=False)
        
        submit_btn.bind(on_press=self.process_popup_result)
        cancel_btn.bind(on_press=self.startup_popup.dismiss)
        
        self.startup_popup.open()
        
    def process_popup_result(self, instance):
        text = self.popup_input.text.strip()
        self.startup_popup.dismiss()
        if text and text.isdigit():
            calories = text
            if self.root and hasattr(self.root, 'get_screen'):
                tracker_screen = self.root.get_screen('calorie_tracker')
                if tracker_screen and tracker_screen.tracker_instance:
                    tracker = tracker_screen.tracker_instance
                    if hasattr(tracker, 'ids') and tracker.ids:
                        for i in range(1, 7):
                            meal_id = f'meal{i}_input'
                            if meal_id in tracker.ids:
                                widget = tracker.ids[meal_id]
                                if not widget.text.strip():
                                    widget.text = calories
                                    tracker.save_temp_data_on_change(widget, calories)
                                    tracker.update_total_calories()
                                    if 'status_label' in tracker.ids:
                                        tracker.ids.status_label.text = f"Popup input: {calories} added to Meal {i}"
                                        tracker.ids.status_label.color = (0.1, 0.7, 0.2, 1)
                                    return
                        
                        if 'status_label' in tracker.ids:
                            tracker.ids.status_label.text = "Popup input: All meal slots are full."
                            tracker.ids.status_label.color = (0.8, 0.5, 0.1, 1)

if __name__ == '__main__':
    Logger.info("Application Start")
    CalorieTrackerApp().run()