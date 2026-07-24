# PythonAnywhere Deployment Guide (git clone)

## 1. Clone Repository

Open a **Bash console** on PythonAnywhere and run:

```bash
cd ~ && git clone https://github.com/molszewski9412-source/swapper.git
```

## 2. Install Dependencies

```bash
cd ~/swapper
pip install -r requirements.txt
```

## 3. Configure Web App

1. Go to **Web** tab on PythonAnywhere
2. Click **Add new web app**
3. Choose **Flask** and Python 3.11
4. For "Source file" - change to: `/home/TWOJ_USERNAME/swapper/backtest_app.py`
5. Click Next and finish

## 4. Edit WSGI File

Edit the WSGI file (click on the link in Web tab):

```python
import sys

# Change TWOJ_USERNAME to your PythonAnywhere username
path = '/home/TWOJ_USERNAME/swapper'
if path not in sys.path:
    sys.path.insert(0, path)

from backtest_app import app as application
```

## 5. Set Working Directory (optional)

In the Web configuration, set:
- **Working directory**: `/home/TWOJ_USERNAME/swapper`

## 6. Reload

Click **Reload** button on the Web tab.

## 7. Done!

Your app is now live at: `https://twoj_username.pythonanywhere.com`

## Update Deployment

To update after code changes:

```bash
cd ~/swapper
git pull
# Reload the web app from the Web tab
```

## Notes

- Database `backtest.db` will be created automatically
- All data is stored in the SQLite database file
