[app]

# (str) Title of your application
title = Calorie Tracker

# (str) Package name
package.name = calorietracker

# (str) Package domain (needed for android/ios packaging)
package.domain = org.josemarichal

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas

# (list) List of exclusions using pattern matching
source.exclude_dirs = tests, bin, venv, build, dist, app_data, .git, .github, __pycache__

# (str) Application versioning (method 1)
version = 0.2

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,kivy,pyjnius

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) Permissions
android.permissions = WRITE_EXTERNAL_STORAGE, READ_EXTERNAL_STORAGE

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (str) Application icon
icon.filename = %(source.dir)s/scale.png

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK / AAB will support
android.minapi = 21

# (str) Android NDK version to use (let Buildozer use python-for-android's recommended NDK automatically)
#android.ndk = 28c

# (bool) If True, then automatically accept SDK license
android.accept_sdk_license = True

# (str) Android entry point, default is ok for Kivy-based app
android.entrypoint = org.kivy.android.PythonActivity

# (list) Build for 64-bit ARM (modern Android phones; avoids 32-bit armeabi-v7a failure on Python 3.14)
android.archs = arm64-v8a

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 1

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
