# PythonAnywhere Deployment Guide

## 1. Setup on PythonAnywhere

### Upload Files
Upload the following files/folders to your PythonAnywhere account:
- `backtest_app.py`
- `templates/` folder
- `requirements.txt`

### Create Virtual Environment (optional but recommended)
```
mkvirtualenv --python=python3.11 swapper
pip install -r requirements.txt
```

### Configure Web App

1. Go to **Web** tab
2. Add new web app
3. Choose **Flask** and Python 3.11
4. Edit WSGI file:
   ```python
   import sys
   path = '/home/YOUR_USERNAME/swapper'
   if path not in sys.path:
       sys.path.insert(0, path)
   from backtest_app import app as application
   ```

5. Set virtual env (if using one)

## 2. Configuration

The app runs on port 8080 by default. PythonAnywhere handles this automatically.

## 3. Run

After configuration, reload the web app.

Your app will be available at: `https://YOUR_USERNAME.pythonanywhere.com`

## 4. Files Required

- `backtest_app.py` - Main Flask application
- `templates/backtest.html` - Frontend interface
- `requirements.txt` - Dependencies

## 5. Database

The app will automatically create `backtest.db` SQLite database on first run.
