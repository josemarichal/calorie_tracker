import os
import sys
import sqlite3
from datetime import date, timedelta, datetime

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.utils import platform
from kivy.logger import Logger
from kivy.metrics import dp
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.properties import (
    ObjectProperty,
    NumericProperty,
    StringProperty,
    ListProperty,
    BooleanProperty,
)
from kivy.uix.behaviors import ButtonBehavior

# Flag to track if we can access the required storage
STORAGE_ACCESS_OK = True
DB_FILE = None

MEAL_NAMES = [
    "1: Breakfast",
    "2: Lunch",
    "3: Dinner",
    "4: Snack 1",
    "5: Snack 2",
    "6: Snack 3",
]


def get_database_path():
    """Gets the appropriate database path for the platform."""
    global STORAGE_ACCESS_OK
    db_dir_to_use = None

    if platform == 'android':
        try:
            context = App.get_running_app()
            if context and hasattr(context, 'user_data_dir') and context.user_data_dir:
                db_dir_to_use = context.user_data_dir
                Logger.info(f"Using Android Internal Storage (user_data_dir): {db_dir_to_use}")
            else:
                from android.storage import app_storage_path
                app_path = app_storage_path()
                if app_path:
                    db_dir_to_use = os.path.join(app_path, context.name if context else "app")
                    Logger.info(f"Using Android Internal Storage (app_storage_path fallback): {db_dir_to_use}")
                else:
                    Logger.error("Android: Could not retrieve user_data_dir or app_storage_path.")
                    STORAGE_ACCESS_OK = False
                    return None
        except Exception as e:
            Logger.error(f"Android: Error getting internal data path: {e}")
            STORAGE_ACCESS_OK = False
            return None
    else:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            db_dir_to_use = os.path.join(script_dir, "app_data")
            Logger.info(f"Using Desktop path: {db_dir_to_use}")
        except Exception as e:
            Logger.error(f"Desktop: Error determining app data path: {e}")
            STORAGE_ACCESS_OK = False
            return None

    if db_dir_to_use:
        try:
            if not os.path.exists(db_dir_to_use):
                os.makedirs(db_dir_to_use)
        except Exception as e:
            Logger.error(f"Failed to create directory {db_dir_to_use}: {e}")
            STORAGE_ACCESS_OK = False
            return None

        if not os.access(db_dir_to_use, os.W_OK | os.X_OK):
            Logger.error(f"Directory is not writable/accessible: {db_dir_to_use}")
            STORAGE_ACCESS_OK = False
            return None

        db_path = os.path.join(db_dir_to_use, "calorie_data.db")
        Logger.info(f"Database Path Set To: {db_path}")
        return db_path
    else:
        STORAGE_ACCESS_OK = False
        return None


def init_db():
    """Initialize and safely migrate the SQLite database."""
    global DB_FILE, STORAGE_ACCESS_OK

    if not STORAGE_ACCESS_OK or not DB_FILE:
        Logger.error("init_db: Cannot initialize, storage access issue or DB_FILE not set.")
        return False
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute('''CREATE TABLE IF NOT EXISTS calorie_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Date TEXT UNIQUE NOT NULL,
            Weight REAL,
            Meal1 INTEGER DEFAULT 0,
            Meal2 INTEGER DEFAULT 0,
            Meal3 INTEGER DEFAULT 0,
            Meal4 INTEGER DEFAULT 0,
            Meal5 INTEGER DEFAULT 0,
            Meal6 INTEGER DEFAULT 0,
            TotalCalories INTEGER DEFAULT 0
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS temp_inputs (
            date TEXT PRIMARY KEY,
            weight TEXT,
            meal1 TEXT,
            meal2 TEXT,
            meal3 TEXT,
            meal4 TEXT,
            meal5 TEXT,
            meal6 TEXT
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS user_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')

        # Safe migration for Meal6 on older tables
        for tbl, col_def in [("calorie_data", "Meal6 INTEGER DEFAULT 0"), ("temp_inputs", "meal6 TEXT")]:
            try:
                cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass

        # Deduplicate any historical duplicate Date rows before enforcing unique index
        cursor.execute('''
            DELETE FROM calorie_data
            WHERE id NOT IN (
                SELECT MAX(id) FROM calorie_data GROUP BY Date
            )
        ''')
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_calorie_data_date ON calorie_data(Date)")

        # Migrate any unsaved temp_inputs into calorie_data so past partial entries aren't lost
        cursor.execute("SELECT date, weight, meal1, meal2, meal3, meal4, meal5, meal6 FROM temp_inputs")
        temp_rows = cursor.fetchall()
        for trow in temp_rows:
            t_date = (trow[0] or "").strip()
            if not t_date:
                continue
            try:
                datetime.strptime(t_date, "%Y-%m-%d")
            except ValueError:
                continue

            cursor.execute("SELECT id FROM calorie_data WHERE Date = ?", (t_date,))
            if cursor.fetchone() is None:
                try:
                    w_val = float(trow[1]) if trow[1] and trow[1].strip() else None
                except ValueError:
                    w_val = None
                meals = []
                for m_str in trow[2:8]:
                    try:
                        meals.append(int(float(m_str.strip())) if m_str and m_str.strip() else 0)
                    except ValueError:
                        meals.append(0)
                total_c = sum(meals)
                if w_val is not None or total_c > 0:
                    cursor.execute(
                        '''INSERT INTO calorie_data
                           (Date, Weight, Meal1, Meal2, Meal3, Meal4, Meal5, Meal6, TotalCalories)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (t_date, w_val, meals[0], meals[1], meals[2], meals[3], meals[4], meals[5], total_c),
                    )
        cursor.execute("DELETE FROM temp_inputs")

        conn.commit()
        conn.close()
        Logger.info(f"Database initialized/verified successfully at {DB_FILE}")
        return True
    except Exception as e:
        Logger.exception(f"General database initialization error at {DB_FILE}: {e}")
        STORAGE_ACCESS_OK = False
        return False


class MealSlotCard(ButtonBehavior, BoxLayout):
    slot_index = NumericProperty(1)
    meal_title = StringProperty("1: Meal 1")
    calories_val = NumericProperty(0)
    is_selected = BooleanProperty(False)


class HistoryRowCard(ButtonBehavior, BoxLayout):
    date_str = StringProperty("")
    display_date = StringProperty("")
    total_cals_text = StringProperty("")
    meals_summary_text = StringProperty("")
    weight_text = StringProperty("")


class CalorieTracker(BoxLayout):
    selected_date_str = StringProperty("")
    display_date_title = StringProperty("Today")
    display_date_subtitle = StringProperty("")
    is_today = BooleanProperty(True)

    active_meal_slot = NumericProperty(1)
    active_meal_name = StringProperty(MEAL_NAMES[0])
    numpad_buffer = StringProperty("")
    numpad_display_text = StringProperty("Tap digits or +Quick Add")

    total_calories = NumericProperty(0)
    daily_goal = NumericProperty(2000)
    remaining_text = StringProperty("2,000 kcal left")
    progress_ratio = NumericProperty(0.0)
    progress_Color = ListProperty([0.22, 0.78, 0.52, 1])

    current_weight_display = StringProperty("--.- lbs")
    weight_is_inherited = BooleanProperty(False)
    status_message = StringProperty("Auto-save active")
    status_color = ListProperty([0.58, 0.64, 0.72, 1])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._data_loaded_once = False
        self.data = []
        self.meal_values = [0, 0, 0, 0, 0, 0]
        self.current_weight = None
        self.last_known_weight = 185.0
        self.stats_cache = {
            'wc7': "N/A", 'wc14': "N/A", 'wc30': "N/A",
            'ac7': "N/A", 'ac14': "N/A", 'ac30': "N/A"
        }

    def check_storage_and_load(self):
        global STORAGE_ACCESS_OK
        if not STORAGE_ACCESS_OK:
            self.set_status("Storage Error - Cannot Load Data", is_error=True)
            return
        self.load_data_and_ui()

    def set_status(self, msg, is_error=False, is_success=False):
        self.status_message = msg
        if is_error:
            self.status_color = [0.95, 0.35, 0.35, 1]
        elif is_success:
            self.status_color = [0.25, 0.85, 0.55, 1]
        else:
            self.status_color = [0.58, 0.64, 0.72, 1]

    def load_data_and_ui(self):
        global DB_FILE, STORAGE_ACCESS_OK
        if not STORAGE_ACCESS_OK or not DB_FILE:
            self.set_status("Storage Error", is_error=True)
            return

        try:
            self.load_settings()
            self.load_data()
            self.calculate_summary_stats()

            today_str = datetime.now().strftime("%Y-%m-%d")
            self.load_day(today_str, auto_select_empty=True)
            self._data_loaded_once = True
            self.set_status("All changes save automatically")
        except Exception as e:
            Logger.exception(f"Error during load_data_and_ui: {e}")
            self.set_status(f"Load Error: {type(e).__name__}", is_error=True)

    def load_settings(self):
        if not STORAGE_ACCESS_OK or not DB_FILE:
            return
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM user_settings WHERE key = 'daily_goal'")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                self.daily_goal = max(800, min(10000, int(row[0])))
        except Exception as e:
            Logger.warning(f"Could not load settings: {e}")

    def save_setting(self, key, value):
        if not STORAGE_ACCESS_OK or not DB_FILE:
            return
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO user_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
            conn.close()
        except Exception as e:
            Logger.warning(f"Could not save setting {key}: {e}")

    def adjust_daily_goal(self, delta):
        new_goal = max(1000, min(6000, self.daily_goal + delta))
        self.daily_goal = new_goal
        self.save_setting('daily_goal', new_goal)
        self.refresh_summary_ui()

    def load_data(self):
        """Load all historical records from SQLite into self.data sorted by Date ASC."""
        self.data = []
        if not STORAGE_ACCESS_OK or not DB_FILE or not os.path.exists(DB_FILE):
            return

        try:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT Date, Weight, Meal1, Meal2, Meal3, Meal4, Meal5, Meal6, TotalCalories "
                "FROM calorie_data ORDER BY Date ASC"
            )
            rows = cursor.fetchall()
            conn.close()

            temp_list = []
            latest_w = None
            for row in rows:
                try:
                    date_obj = datetime.strptime(row['Date'], "%Y-%m-%d").date()
                    weight = float(row['Weight']) if row['Weight'] is not None else None
                    if weight is not None and weight > 0:
                        latest_w = weight
                    meals = [
                        int(row[f'Meal{i}']) if row[f'Meal{i}'] is not None else 0
                        for i in range(1, 7)
                    ]
                    total_cals = sum(meals)
                    temp_list.append({
                        'Date': date_obj,
                        'DateStr': row['Date'],
                        'Weight': weight,
                        'Meal1': meals[0], 'Meal2': meals[1], 'Meal3': meals[2],
                        'Meal4': meals[3], 'Meal5': meals[4], 'Meal6': meals[5],
                        'TotalCalories': total_cals,
                    })
                except (ValueError, TypeError) as err:
                    Logger.error(f"Skipping malformed row {row}: {err}")

            self.data = temp_list
            if latest_w is not None:
                self.last_known_weight = latest_w
        except Exception as e:
            Logger.exception(f"Error loading data: {e}")

    def load_day(self, date_str, auto_select_empty=True):
        """Load a specific YYYY-MM-DD date into the UI."""
        try:
            target_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return

        self.selected_date_str = date_str
        today_dt = datetime.now().date()
        self.is_today = (target_dt == today_dt)

        if target_dt == today_dt:
            self.display_date_title = "Today"
        elif target_dt == today_dt - timedelta(days=1):
            self.display_date_title = "Yesterday"
        elif target_dt == today_dt + timedelta(days=1):
            self.display_date_title = "Tomorrow"
        else:
            self.display_date_title = target_dt.strftime("%b %d, %Y")

        self.display_date_subtitle = target_dt.strftime("%A, %b %d")

        # Find record for date_str
        record = None
        for entry in self.data:
            if entry['DateStr'] == date_str:
                record = entry
                break

        if record:
            self.meal_values = [record[f'Meal{i}'] for i in range(1, 7)]
            self.current_weight = record['Weight']
            self.weight_is_inherited = False
        else:
            self.meal_values = [0, 0, 0, 0, 0, 0]
            self.current_weight = None
            self.weight_is_inherited = True

        if auto_select_empty:
            # Automatically highlight the first empty meal slot (1..6), or slot 6 if all filled
            first_empty = 6
            for idx, val in enumerate(self.meal_values):
                if val == 0:
                    first_empty = idx + 1
                    break
            self.select_meal_slot(first_empty, clear_buffer=True)
        else:
            self.select_meal_slot(self.active_meal_slot, clear_buffer=False)

        self.refresh_summary_ui()

    def change_day(self, delta_days):
        try:
            curr_dt = datetime.strptime(self.selected_date_str, "%Y-%m-%d").date()
        except ValueError:
            curr_dt = datetime.now().date()
        new_dt = curr_dt + timedelta(days=delta_days)
        self.load_day(new_dt.strftime("%Y-%m-%d"), auto_select_empty=True)

    def jump_to_today(self):
        today_str = datetime.now().strftime("%Y-%m-%d")
        self.load_day(today_str, auto_select_empty=True)

    def select_meal_slot(self, slot_idx, clear_buffer=True):
        slot_idx = max(1, min(6, int(slot_idx)))
        self.active_meal_slot = slot_idx
        self.active_meal_name = MEAL_NAMES[slot_idx - 1]
        if clear_buffer:
            self.numpad_buffer = ""
        self.update_numpad_display()
        self.refresh_meal_cards()

    def update_numpad_display(self):
        current_slot_val = self.meal_values[self.active_meal_slot - 1]
        if self.numpad_buffer:
            self.numpad_display_text = f"{self.numpad_buffer} kcal"
        elif current_slot_val > 0:
            self.numpad_display_text = f"Current: {current_slot_val} kcal (type to replace or +Add)"
        else:
            self.numpad_display_text = "Tap +Quick Add or type calories"

    def refresh_meal_cards(self):
        if not hasattr(self, 'ids') or not self.ids:
            return
        for i in range(1, 7):
            card_id = f'meal_card_{i}'
            if card_id in self.ids:
                card = self.ids[card_id]
                card.calories_val = self.meal_values[i - 1]
                card.is_selected = (self.active_meal_slot == i)

    def refresh_summary_ui(self):
        self.refresh_meal_cards()
        total = sum(self.meal_values)
        self.total_calories = total

        diff = self.daily_goal - total
        if diff >= 0:
            self.remaining_text = f"{diff:,} kcal left of {self.daily_goal:,}"
        else:
            self.remaining_text = f"{abs(diff):,} kcal over {self.daily_goal:,} goal"

        ratio = float(total) / float(self.daily_goal) if self.daily_goal > 0 else 0.0
        self.progress_ratio = min(1.0, max(0.0, ratio))

        if ratio <= 0.85:
            self.progress_Color = [0.22, 0.78, 0.52, 1]  # Emerald green
        elif ratio <= 1.0:
            self.progress_Color = [0.95, 0.68, 0.20, 1]  # Warm amber
        else:
            self.progress_Color = [0.95, 0.35, 0.35, 1]  # Coral red

        if self.current_weight is not None and self.current_weight > 0:
            self.current_weight_display = f"{self.current_weight:.1f} lbs"
            self.weight_is_inherited = False
        else:
            self.current_weight_display = f"{self.last_known_weight:.1f} lbs (last)"
            self.weight_is_inherited = True

        self.update_numpad_display()

    def persist_current_day(self):
        """Immediately auto-save the current day's meals and weight to SQLite."""
        if not STORAGE_ACCESS_OK or not DB_FILE or not self.selected_date_str:
            return
        try:
            total_cals = sum(self.meal_values)
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            if total_cals == 0 and self.current_weight is None:
                # If everything was cleared for this date, remove the empty row
                cursor.execute("DELETE FROM calorie_data WHERE Date = ?", (self.selected_date_str,))
            else:
                # Fixed 9-column, 9-placeholder upsert
                cursor.execute(
                    '''INSERT INTO calorie_data
                       (Date, Weight, Meal1, Meal2, Meal3, Meal4, Meal5, Meal6, TotalCalories)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(Date) DO UPDATE SET
                           Weight = excluded.Weight,
                           Meal1 = excluded.Meal1,
                           Meal2 = excluded.Meal2,
                           Meal3 = excluded.Meal3,
                           Meal4 = excluded.Meal4,
                           Meal5 = excluded.Meal5,
                           Meal6 = excluded.Meal6,
                           TotalCalories = excluded.TotalCalories''',
                    (
                        self.selected_date_str,
                        self.current_weight,
                        self.meal_values[0],
                        self.meal_values[1],
                        self.meal_values[2],
                        self.meal_values[3],
                        self.meal_values[4],
                        self.meal_values[5],
                        total_cals,
                    ),
                )
            conn.commit()
            conn.close()

            self.load_data()
            self.calculate_summary_stats()
            self.refresh_summary_ui()
        except Exception as e:
            Logger.exception(f"Error auto-saving day {self.selected_date_str}: {e}")
            self.set_status(f"Save Error: {type(e).__name__}", is_error=True)

    # --- Quick-Add & Built-in Numpad Actions ---
    def quick_add_calories(self, amount):
        """One-tap increment on the currently active meal slot."""
        idx = self.active_meal_slot - 1
        new_val = max(0, self.meal_values[idx] + int(amount))
        self.meal_values[idx] = new_val
        self.numpad_buffer = ""
        self.persist_current_day()
        sign = f"+{amount}" if amount > 0 else f"{amount}"
        self.set_status(
            f"Saved! {sign} kcal -> Meal {self.active_meal_slot} ({new_val} kcal)",
            is_success=True,
        )

    def clear_active_meal(self):
        idx = self.active_meal_slot - 1
        self.meal_values[idx] = 0
        self.numpad_buffer = ""
        self.persist_current_day()
        self.set_status(f"Cleared Meal {self.active_meal_slot}")

    def numpad_press(self, key):
        if key == 'BS':
            self.numpad_buffer = self.numpad_buffer[:-1]
        elif key == 'CLR':
            self.numpad_buffer = ""
        elif key == '.':
            if '.' not in self.numpad_buffer:
                self.numpad_buffer = (self.numpad_buffer or "0") + "."
        else:
            if len(self.numpad_buffer) < 5:
                if self.numpad_buffer == "0":
                    self.numpad_buffer = str(key)
                else:
                    self.numpad_buffer += str(key)
        self.update_numpad_display()

    def commit_numpad_to_meal(self, add_mode=False):
        """Log the numpad buffer to the active meal and auto-advance to the next empty meal."""
        idx = self.active_meal_slot - 1
        if not self.numpad_buffer:
            # If buffer is empty and user presses Next/Log, just advance to next meal slot
            next_slot = (self.active_meal_slot % 6) + 1
            self.select_meal_slot(next_slot, clear_buffer=True)
            self.set_status(f"Switched to {MEAL_NAMES[next_slot - 1]}")
            return

        try:
            cals = int( round(float(self.numpad_buffer)) )
        except ValueError:
            self.set_status("Invalid calorie number", is_error=True)
            return

        if add_mode:
            self.meal_values[idx] = max(0, self.meal_values[idx] + cals)
            action_desc = f"+{cals} kcal added to Meal {self.active_meal_slot}"
        else:
            self.meal_values[idx] = max(0, cals)
            action_desc = f"Meal {self.active_meal_slot} set to {cals} kcal"

        self.numpad_buffer = ""
        self.persist_current_day()

        # Auto-advance to the next empty meal slot for frictionless sequential logging
        next_empty = None
        for offset in range(1, 7):
            candidate = ((idx + offset) % 6)
            if self.meal_values[candidate] == 0:
                next_empty = candidate + 1
                break
        if next_empty:
            self.select_meal_slot(next_empty, clear_buffer=True)

        self.set_status(f"Saved! {action_desc}", is_success=True)

    # --- Frictionless Weight Logging ---
    def step_weight(self, delta):
        base_w = self.current_weight if (self.current_weight is not None and self.current_weight > 0) else self.last_known_weight
        new_w = round(max(50.0, min(600.0, base_w + delta)), 1)
        self.current_weight = new_w
        self.last_known_weight = new_w
        self.persist_current_day()
        self.set_status(f"Saved weight: {new_w:.1f} lbs", is_success=True)

    def set_weight_from_numpad(self):
        if not self.numpad_buffer:
            # Log the displayed last_known_weight for today with 1 tap
            self.current_weight = round(self.last_known_weight, 1)
            self.persist_current_day()
            self.set_status(f"Logged weight: {self.current_weight:.1f} lbs", is_success=True)
            return
        try:
            val = round(float(self.numpad_buffer), 1)
            if 40.0 <= val <= 700.0:
                self.current_weight = val
                self.last_known_weight = val
                self.numpad_buffer = ""
                self.persist_current_day()
                self.set_status(f"Saved weight: {val:.1f} lbs", is_success=True)
            else:
                self.set_status("Enter a weight between 40 and 700 lbs on keypad first", is_error=True)
        except ValueError:
            self.set_status("Invalid weight number", is_error=True)

    def calculate_summary_stats(self):
        """Calculate 7, 14, and 30 day summary statistics."""
        if not self.data:
            self.stats_cache = {key: "N/A" for key in self.stats_cache}
            return

        try:
            latest_entry_date = self.data[-1]['Date']

            for period_days in [7, 14, 30]:
                start_period_date = latest_entry_date - timedelta(days=period_days - 1)
                period_entries = [
                    entry for entry in self.data
                    if start_period_date <= entry['Date'] <= latest_entry_date
                ]

                calories_in_period = [
                    entry['TotalCalories'] for entry in period_entries
                    if entry.get('TotalCalories') and entry['TotalCalories'] > 0
                ]
                if calories_in_period:
                    avg_cals = sum(calories_in_period) / len(calories_in_period)
                    self.stats_cache[f'ac{period_days}'] = f"{avg_cals:,.0f}"
                else:
                    self.stats_cache[f'ac{period_days}'] = "N/A"

                weights_in_period = [
                    entry for entry in period_entries
                    if entry.get('Weight') is not None and entry['Weight'] > 0
                ]
                if len(weights_in_period) >= 2:
                    current_w = max(weights_in_period, key=lambda x: x['Date'])['Weight']
                    start_w = min(weights_in_period, key=lambda x: x['Date'])['Weight']
                    weight_change = current_w - start_w
                    self.stats_cache[f'wc{period_days}'] = f"{weight_change:+.1f} lbs"
                elif len(weights_in_period) == 1:
                    self.stats_cache[f'wc{period_days}'] = "0.0 lbs"
                else:
                    self.stats_cache[f'wc{period_days}'] = "N/A"
        except Exception as e:
            Logger.exception(f"Error calculating summary stats: {e}")
            self.stats_cache = {key: "N/A" for key in self.stats_cache}


class CalorieTrackerScreen(Screen):
    tracker_instance = ObjectProperty(None)


class ProgressScreen(Screen):
    daily_goal_text = StringProperty("2,000 kcal")

    def on_enter(self):
        app = App.get_running_app()
        if app and app.root and hasattr(app.root, 'get_screen'):
            try:
                tracker_screen = app.root.get_screen('calorie_tracker')
                if tracker_screen and tracker_screen.tracker_instance:
                    tracker = tracker_screen.tracker_instance
                    tracker.calculate_summary_stats()
                    self.daily_goal_text = f"{tracker.daily_goal:,} kcal"
            except Exception as e:
                Logger.error(f"ProgressScreen: Error refreshing stats: {e}")
        self.update_display()

    def adjust_goal(self, delta):
        app = App.get_running_app()
        if app and app.root:
            tracker = app.root.get_screen('calorie_tracker').tracker_instance
            if tracker:
                tracker.adjust_daily_goal(delta)
                self.daily_goal_text = f"{tracker.daily_goal:,} kcal"

    def update_display(self):
        app = App.get_running_app()
        tracker = None
        if app and app.root:
            tracker = app.root.get_screen('calorie_tracker').tracker_instance
        if not tracker or not hasattr(self, 'ids') or not self.ids:
            return

        stats = tracker.stats_cache
        self.ids.ps_weight_change_7.text = stats.get('wc7', "N/A")
        self.ids.ps_weight_change_14.text = stats.get('wc14', "N/A")
        self.ids.ps_weight_change_30.text = stats.get('wc30', "N/A")
        self.ids.ps_avg_calories_7.text = stats.get('ac7', "N/A")
        self.ids.ps_avg_calories_14.text = stats.get('ac14', "N/A")
        self.ids.ps_avg_calories_30.text = stats.get('ac30', "N/A")

        self.apply_stat_coloring(self.ids.ps_weight_change_7)
        self.apply_stat_coloring(self.ids.ps_weight_change_14)
        self.apply_stat_coloring(self.ids.ps_weight_change_30)

        # Populate recent history list (latest 20 days reversed)
        history_box = self.ids.get('history_list_box')
        if history_box is not None:
            history_box.clear_widgets()
            recent_entries = list(reversed(tracker.data[-20:]))
            if not recent_entries:
                history_box.add_widget(
                    Label(
                        text="No logged days yet. Tap any meal on the main screen to start!",
                        color=(0.6, 0.65, 0.72, 1),
                        font_size='14sp',
                        size_hint_y=None,
                        height=dp(44),
                    )
                )
            else:
                for entry in recent_entries:
                    row = HistoryRowCard()
                    row.date_str = entry['DateStr']
                    row.display_date = entry['Date'].strftime("%a, %b %d")
                    row.total_cals_text = f"{entry['TotalCalories']:,} kcal"
                    meals_non_zero = [
                        f"M{i}:{entry[f'Meal{i}']}"
                        for i in range(1, 7)
                        if entry.get(f'Meal{i}', 0) > 0
                    ]
                    row.meals_summary_text = "  ".join(meals_non_zero) if meals_non_zero else "No meals logged"
                    row.weight_text = f"{entry['Weight']:.1f} lbs" if entry.get('Weight') else "--"
                    row.bind(on_release=self.on_history_row_tap)
                    history_box.add_widget(row)

    def on_history_row_tap(self, row_widget):
        app = App.get_running_app()
        if app and app.root:
            tracker = app.root.get_screen('calorie_tracker').tracker_instance
            if tracker and row_widget.date_str:
                tracker.load_day(row_widget.date_str, auto_select_empty=True)
                self.manager.transition = SlideTransition(direction='right')
                self.manager.current = 'calorie_tracker'

    def apply_stat_coloring(self, label_widget):
        default_color = (0.85, 0.88, 0.92, 1)
        loss_color = (0.25, 0.85, 0.55, 1)
        gain_color = (0.95, 0.45, 0.40, 1)
        try:
            text_val = label_widget.text
            if "N/A" in text_val or "lbs" not in text_val:
                label_widget.color = default_color
                return
            numeric_part = text_val.replace("lbs", "").replace("+", "").strip()
            value = float(numeric_part)
            if value < 0:
                label_widget.color = loss_color
            elif value > 0:
                label_widget.color = gain_color
            else:
                label_widget.color = default_color
        except Exception:
            label_widget.color = default_color

    def go_back(self):
        self.manager.transition = SlideTransition(direction='right')
        self.manager.current = 'calorie_tracker'


KV_STRING = """
#:import dp kivy.metrics.dp
#:import SlideTransition kivy.uix.screenmanager.SlideTransition

<QuickChipButton@Button>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: 0.92, 0.96, 1, 1
    font_size: '14sp'
    bold: True
    canvas.before:
        Color:
            rgba: (0.22, 0.52, 0.88, 1) if self.state == 'down' else (0.17, 0.23, 0.34, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
        Color:
            rgba: 0.28, 0.38, 0.55, 1
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(10))
            width: 1

<NumpadKey@Button>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: 0.96, 0.97, 0.99, 1
    font_size: '20sp'
    bold: True
    canvas.before:
        Color:
            rgba: (0.25, 0.33, 0.46, 1) if self.state == 'down' else (0.14, 0.18, 0.25, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]

<WeightStepButton@Button>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: 0.88, 0.92, 0.98, 1
    font_size: '13sp'
    bold: True
    size_hint_x: None
    width: dp(46)
    canvas.before:
        Color:
            rgba: (0.25, 0.35, 0.50, 1) if self.state == 'down' else (0.16, 0.21, 0.30, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]

<MealSlotCard>:
    orientation: 'vertical'
    padding: [dp(8), dp(6)]
    spacing: dp(2)
    canvas.before:
        Color:
            rgba: (0.16, 0.27, 0.42, 1) if root.is_selected else ((0.12, 0.17, 0.24, 1) if root.calories_val > 0 else (0.10, 0.13, 0.19, 1))
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: (0.30, 0.72, 1.0, 1) if root.is_selected else ((0.22, 0.55, 0.40, 0.7) if root.calories_val > 0 else (0.18, 0.23, 0.32, 1))
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(12))
            width: dp(1.8) if root.is_selected else dp(1)
    Label:
        text: root.meal_title
        font_size: '11sp'
        bold: True
        color: (0.55, 0.82, 1.0, 1) if root.is_selected else (0.58, 0.65, 0.75, 1)
        size_hint_y: 0.42
        halign: 'center'
        valign: 'middle'
        text_size: self.size
    Label:
        text: (str(root.calories_val) + ' kcal') if root.calories_val > 0 else '+ Tap'
        font_size: '16sp' if root.calories_val > 0 else '13sp'
        bold: root.calories_val > 0
        color: (1, 1, 1, 1) if root.calories_val > 0 else ((0.65, 0.82, 1.0, 0.9) if root.is_selected else (0.42, 0.48, 0.58, 1))
        size_hint_y: 0.58
        halign: 'center'
        valign: 'middle'
        text_size: self.size

<HistoryRowCard>:
    orientation: 'horizontal'
    size_hint_y: None
    height: dp(58)
    padding: [dp(12), dp(8)]
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: (0.18, 0.24, 0.34, 1) if self.state == 'down' else (0.12, 0.16, 0.23, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
    BoxLayout:
        orientation: 'vertical'
        size_hint_x: 0.56
        Label:
            text: root.display_date
            font_size: '14sp'
            bold: True
            color: 0.94, 0.96, 1, 1
            halign: 'left'
            valign: 'middle'
            text_size: self.size
        Label:
            text: root.meals_summary_text
            font_size: '11sp'
            color: 0.58, 0.65, 0.75, 1
            halign: 'left'
            valign: 'middle'
            text_size: self.size
            shorten: True
            shorten_from: 'right'
    BoxLayout:
        orientation: 'vertical'
        size_hint_x: 0.44
        Label:
            text: root.total_cals_text
            font_size: '15sp'
            bold: True
            color: 0.30, 0.82, 0.58, 1
            halign: 'right'
            valign: 'middle'
            text_size: self.size
        Label:
            text: root.weight_text
            font_size: '12sp'
            color: 0.68, 0.75, 0.85, 1
            halign: 'right'
            valign: 'middle'
            text_size: self.size

<CalorieTrackerScreen>:
    tracker_instance: tracker_content_id
    CalorieTracker:
        id: tracker_content_id

<CalorieTracker>:
    orientation: 'vertical'
    padding: [dp(12), dp(10), dp(12), dp(8)]
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: 0.06, 0.08, 0.12, 1
        Rectangle:
            pos: self.pos
            size: self.size

    # --- 1. Top Date Navigation & Stats Header ---
    BoxLayout:
        orientation: 'horizontal'
        size_hint_y: None
        height: dp(44)
        spacing: dp(6)

        Button:
            text: '<'
            font_size: '20sp'
            bold: True
            size_hint_x: None
            width: dp(44)
            background_normal: ''
            background_down: ''
            background_color: 0, 0, 0, 0
            color: 0.9, 0.94, 1, 1
            on_release: root.change_day(-1)
            canvas.before:
                Color:
                    rgba: (0.22, 0.30, 0.42, 1) if self.state == 'down' else (0.13, 0.17, 0.24, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(10)]

        Button:
            background_normal: ''
            background_down: ''
            background_color: 0, 0, 0, 0
            on_release: root.jump_to_today()
            canvas.before:
                Color:
                    rgba: (0.16, 0.22, 0.32, 1) if self.state == 'down' else (0.11, 0.15, 0.22, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(10)]
            BoxLayout:
                pos: self.parent.pos
                size: self.parent.size
                orientation: 'vertical'
                padding: [dp(6), dp(2)]
                Label:
                    text: root.display_date_title + ("" if root.is_today else "  (Tap for Today)")
                    font_size: '15sp'
                    bold: True
                    color: 0.96, 0.98, 1, 1
                Label:
                    text: root.display_date_subtitle
                    font_size: '11sp'
                    color: 0.58, 0.66, 0.78, 1

        Button:
            text: '>'
            font_size: '20sp'
            bold: True
            size_hint_x: None
            width: dp(44)
            background_normal: ''
            background_down: ''
            background_color: 0, 0, 0, 0
            color: 0.9, 0.94, 1, 1
            on_release: root.change_day(1)
            canvas.before:
                Color:
                    rgba: (0.22, 0.30, 0.42, 1) if self.state == 'down' else (0.13, 0.17, 0.24, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(10)]

        Button:
            text: 'Trends'
            font_size: '13sp'
            bold: True
            size_hint_x: None
            width: dp(68)
            background_normal: ''
            background_down: ''
            background_color: 0, 0, 0, 0
            color: 0.95, 0.98, 1, 1
            on_release:
                app.root.transition = SlideTransition(direction='left')
                app.root.current = 'progress'
            canvas.before:
                Color:
                    rgba: (0.22, 0.48, 0.82, 1) if self.state == 'down' else (0.18, 0.38, 0.68, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(10)]

    # --- 2. Hero Calorie Summary & Progress Bar + Frictionless Weight Bar ---
    BoxLayout:
        orientation: 'vertical'
        size_hint_y: None
        height: dp(104)
        padding: [dp(12), dp(8)]
        spacing: dp(6)
        canvas.before:
            Color:
                rgba: 0.11, 0.15, 0.22, 1
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(14)]

        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: dp(32)
            Label:
                text: '{:,} kcal'.format(root.total_calories)
                font_size: '24sp'
                bold: True
                color: 0.98, 0.99, 1, 1
                halign: 'left'
                valign: 'middle'
                text_size: self.size
                size_hint_x: 0.48
            Label:
                text: root.remaining_text
                font_size: '13sp'
                bold: True
                color: root.progress_Color
                halign: 'right'
                valign: 'middle'
                text_size: self.size
                size_hint_x: 0.52

        # Progress Bar Track
        Widget:
            size_hint_y: None
            height: dp(8)
            canvas:
                Color:
                    rgba: 0.06, 0.08, 0.12, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(4)]
                Color:
                    rgba: root.progress_Color
                RoundedRectangle:
                    pos: self.pos
                    size: (max(dp(6), self.width * root.progress_ratio) if root.total_calories > 0 else 0, self.height)
                    radius: [dp(4)]

        # Frictionless Weight Stepper Row
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: dp(34)
            spacing: dp(5)
            Label:
                text: "Wt: " + root.current_weight_display
                font_size: '13sp'
                bold: True
                color: (0.68, 0.76, 0.88, 1) if root.weight_is_inherited else (0.35, 0.88, 0.62, 1)
                halign: 'left'
                valign: 'middle'
                text_size: self.size
            WeightStepButton:
                text: '-0.5'
                on_release: root.step_weight(-0.5)
            WeightStepButton:
                text: '-0.1'
                on_release: root.step_weight(-0.1)
            WeightStepButton:
                text: '+0.1'
                on_release: root.step_weight(0.1)
            WeightStepButton:
                text: '+0.5'
                on_release: root.step_weight(0.5)
            Button:
                text: 'Set Wt'
                font_size: '12sp'
                bold: True
                size_hint_x: None
                width: dp(54)
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 0.9, 0.95, 1, 1
                on_release: root.set_weight_from_numpad()
                canvas.before:
                    Color:
                        rgba: (0.24, 0.45, 0.72, 1) if self.state == 'down' else (0.18, 0.30, 0.48, 1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(8)]

    # --- 3. 6 Tappable Meal Slot Cards (3x2 Grid) ---
    GridLayout:
        cols: 3
        rows: 2
        spacing: dp(7)
        size_hint_y: None
        height: dp(116)

        MealSlotCard:
            id: meal_card_1
            slot_index: 1
            meal_title: "1: Breakfast"
            on_release: root.select_meal_slot(1)
        MealSlotCard:
            id: meal_card_2
            slot_index: 2
            meal_title: "2: Lunch"
            on_release: root.select_meal_slot(2)
        MealSlotCard:
            id: meal_card_3
            slot_index: 3
            meal_title: "3: Dinner"
            on_release: root.select_meal_slot(3)
        MealSlotCard:
            id: meal_card_4
            slot_index: 4
            meal_title: "4: Snack 1"
            on_release: root.select_meal_slot(4)
        MealSlotCard:
            id: meal_card_5
            slot_index: 5
            meal_title: "5: Snack 2"
            on_release: root.select_meal_slot(5)
        MealSlotCard:
            id: meal_card_6
            slot_index: 6
            meal_title: "6: Snack 3"
            on_release: root.select_meal_slot(6)

    # --- 4. Instant Quick-Add Chips + Thumb Numpad Deck ---
    BoxLayout:
        orientation: 'vertical'
        spacing: dp(6)
        padding: [dp(10), dp(8)]
        canvas.before:
            Color:
                rgba: 0.09, 0.12, 0.18, 1
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [dp(14)]

        # Active Slot Indicator + Live Numpad Readout + Clear Slot Button
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: dp(36)
            spacing: dp(8)

            BoxLayout:
                orientation: 'vertical'
                canvas.before:
                    Color:
                        rgba: 0.06, 0.08, 0.12, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(8)]
                padding: [dp(10), dp(2)]
                Label:
                    text: 'Logging to ' + root.active_meal_name + ':  ' + root.numpad_display_text
                    font_size: '13sp'
                    bold: True
                    color: (0.40, 0.85, 1.0, 1) if root.numpad_buffer else (0.82, 0.88, 0.96, 1)
                    halign: 'left'
                    valign: 'middle'
                    text_size: self.size

            Button:
                text: 'Clear Meal'
                font_size: '12sp'
                bold: True
                size_hint_x: None
                width: dp(78)
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 0.98, 0.72, 0.72, 1
                on_release: root.clear_active_meal()
                canvas.before:
                    Color:
                        rgba: (0.55, 0.20, 0.22, 1) if self.state == 'down' else (0.32, 0.14, 0.17, 1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(8)]

        # One-Tap Quick-Add Row (No typing needed!)
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: dp(38)
            spacing: dp(6)

            QuickChipButton:
                text: '+50'
                on_release: root.quick_add_calories(50)
            QuickChipButton:
                text: '+100'
                on_release: root.quick_add_calories(100)
            QuickChipButton:
                text: '+150'
                on_release: root.quick_add_calories(150)
            QuickChipButton:
                text: '+250'
                on_release: root.quick_add_calories(250)
            QuickChipButton:
                text: '+400'
                on_release: root.quick_add_calories(400)
            QuickChipButton:
                text: '-50'
                color: 0.98, 0.78, 0.78, 1
                on_release: root.quick_add_calories(-50)

        # Built-In Thumb Numpad (Zero Android Keyboard Lag!)
        GridLayout:
            cols: 4
            rows: 4
            spacing: dp(6)

            NumpadKey:
                text: '1'
                on_release: root.numpad_press('1')
            NumpadKey:
                text: '2'
                on_release: root.numpad_press('2')
            NumpadKey:
                text: '3'
                on_release: root.numpad_press('3')
            Button:
                text: 'Del'
                font_size: '16sp'
                bold: True
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 0.95, 0.80, 0.65, 1
                on_release: root.numpad_press('BS')
                canvas.before:
                    Color:
                        rgba: (0.35, 0.25, 0.22, 1) if self.state == 'down' else (0.20, 0.16, 0.16, 1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]

            NumpadKey:
                text: '4'
                on_release: root.numpad_press('4')
            NumpadKey:
                text: '5'
                on_release: root.numpad_press('5')
            NumpadKey:
                text: '6'
                on_release: root.numpad_press('6')
            Button:
                text: '+ Add'
                font_size: '15sp'
                bold: True
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 0.95, 0.98, 1, 1
                on_release: root.commit_numpad_to_meal(add_mode=True)
                canvas.before:
                    Color:
                        rgba: (0.22, 0.52, 0.85, 1) if self.state == 'down' else (0.16, 0.38, 0.65, 1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]

            NumpadKey:
                text: '7'
                on_release: root.numpad_press('7')
            NumpadKey:
                text: '8'
                on_release: root.numpad_press('8')
            NumpadKey:
                text: '9'
                on_release: root.numpad_press('9')
            Button:
                text: 'Log ->'
                font_size: '16sp'
                bold: True
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 1, 1, 1, 1
                on_release: root.commit_numpad_to_meal(add_mode=False)
                canvas.before:
                    Color:
                        rgba: (0.22, 0.78, 0.50, 1) if self.state == 'down' else (0.16, 0.62, 0.38, 1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]

            NumpadKey:
                text: '.'
                on_release: root.numpad_press('.')
            NumpadKey:
                text: '0'
                on_release: root.numpad_press('0')
            NumpadKey:
                text: '00'
                on_release: root.numpad_press('00')
            Button:
                text: 'Next ->'
                font_size: '14sp'
                bold: True
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 0.85, 0.92, 1, 1
                on_release: root.select_meal_slot((root.active_meal_slot % 6) + 1)
                canvas.before:
                    Color:
                        rgba: (0.24, 0.32, 0.44, 1) if self.state == 'down' else (0.16, 0.22, 0.32, 1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]

    # --- 5. Subtle Auto-Save Status Bar ---
    Label:
        text: root.status_message
        font_size: '12sp'
        color: root.status_color
        size_hint_y: None
        height: dp(20)
        halign: 'center'
        valign: 'middle'
        text_size: self.size


<StatCellHeader@Label>:
    bold: True
    font_size: '13sp'
    color: 0.62, 0.70, 0.82, 1
    halign: 'center'
    valign: 'middle'
    text_size: self.size

<StatCellValue@Label>:
    bold: True
    font_size: '15sp'
    color: 0.94, 0.96, 1, 1
    halign: 'center'
    valign: 'middle'
    text_size: self.size

<ProgressScreen>:
    BoxLayout:
        orientation: 'vertical'
        padding: dp(14)
        spacing: dp(10)
        canvas.before:
            Color:
                rgba: 0.06, 0.08, 0.12, 1
            Rectangle:
                pos: self.pos
                size: self.size

        # Top Bar
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: dp(44)
            spacing: dp(10)
            Button:
                text: '< Tracker'
                font_size: '14sp'
                bold: True
                size_hint_x: None
                width: dp(96)
                background_normal: ''
                background_down: ''
                background_color: 0, 0, 0, 0
                color: 0.95, 0.98, 1, 1
                on_release: root.go_back()
                canvas.before:
                    Color:
                        rgba: (0.22, 0.48, 0.82, 1) if self.state == 'down' else (0.16, 0.34, 0.60, 1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]
            Label:
                text: 'Trends & History'
                font_size: '20sp'
                bold: True
                color: 0.96, 0.98, 1, 1
                halign: 'left'
                valign: 'middle'
                text_size: self.size

        # Summary Averages Card
        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: dp(126)
            padding: [dp(12), dp(8)]
            canvas.before:
                Color:
                    rgba: 0.11, 0.15, 0.22, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(14)]

            GridLayout:
                cols: 4
                spacing: dp(4)
                StatCellHeader:
                    text: 'Window'
                    halign: 'left'
                StatCellHeader:
                    text: '7 Days'
                StatCellHeader:
                    text: '14 Days'
                StatCellHeader:
                    text: '30 Days'

                StatCellHeader:
                    text: 'Wt Change'
                    halign: 'left'
                StatCellValue:
                    id: ps_weight_change_7
                    text: 'N/A'
                StatCellValue:
                    id: ps_weight_change_14
                    text: 'N/A'
                StatCellValue:
                    id: ps_weight_change_30
                    text: 'N/A'

                StatCellHeader:
                    text: 'Avg Cals'
                    halign: 'left'
                StatCellValue:
                    id: ps_avg_calories_7
                    text: 'N/A'
                StatCellValue:
                    id: ps_avg_calories_14
                    text: 'N/A'
                StatCellValue:
                    id: ps_avg_calories_30
                    text: 'N/A'

        # Daily Goal Adjuster Card
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: dp(48)
            padding: [dp(12), dp(6)]
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: 0.11, 0.15, 0.22, 1
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(12)]
            Label:
                text: 'Daily Goal: ' + root.daily_goal_text
                font_size: '14sp'
                bold: True
                color: 0.92, 0.96, 1, 1
                halign: 'left'
                valign: 'middle'
                text_size: self.size
            WeightStepButton:
                text: '-100'
                width: dp(54)
                on_release: root.adjust_goal(-100)
            WeightStepButton:
                text: '-50'
                width: dp(48)
                on_release: root.adjust_goal(-50)
            WeightStepButton:
                text: '+50'
                width: dp(48)
                on_release: root.adjust_goal(50)
            WeightStepButton:
                text: '+100'
                width: dp(54)
                on_release: root.adjust_goal(100)

        Label:
            text: 'Recent Days (Tap any day to edit)'
            font_size: '14sp'
            bold: True
            color: 0.65, 0.73, 0.84, 1
            size_hint_y: None
            height: dp(24)
            halign: 'left'
            valign: 'middle'
            text_size: self.size

        ScrollView:
            bar_width: dp(6)
            bar_color: 0.3, 0.5, 0.8, 0.8
            BoxLayout:
                id: history_list_box
                orientation: 'vertical'
                spacing: dp(8)
                size_hint_y: None
                height: self.minimum_height
"""


class CalorieTrackerApp(App):
    def build(self):
        self.title = "Calorie Tracker"
        try:
            Builder.load_string(KV_STRING)
        except Exception as e_kv:
            Logger.exception("CRITICAL: Error loading KV string!")
            return Label(text=f"KV Load Error:\n{e_kv}", halign='center', valign='middle')

        sm = ScreenManager()
        sm.add_widget(CalorieTrackerScreen(name='calorie_tracker'))
        sm.add_widget(ProgressScreen(name='progress'))
        return sm

    def on_start(self):
        global DB_FILE, STORAGE_ACCESS_OK
        DB_FILE = get_database_path()
        if not DB_FILE or not STORAGE_ACCESS_OK:
            Logger.error("App on_start: Failed to get valid DB path or storage access.")
            return

        init_db()
        Clock.schedule_once(self.trigger_tracker_load, 0.1)

    def trigger_tracker_load(self, dt):
        try:
            if self.root and hasattr(self.root, 'get_screen'):
                tracker_screen = self.root.get_screen('calorie_tracker')
                if tracker_screen and tracker_screen.tracker_instance:
                    tracker_instance = tracker_screen.tracker_instance
                    if hasattr(tracker_instance, 'ids') and tracker_instance.ids:
                        tracker_instance.check_storage_and_load()
                    else:
                        Clock.schedule_once(self.trigger_tracker_load, 0.1)
        except Exception as e:
            Logger.exception(f"Error triggering tracker load: {e}")


if __name__ == '__main__':
    CalorieTrackerApp().run()
