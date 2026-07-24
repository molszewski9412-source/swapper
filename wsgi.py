"""
WSGI config for PythonAnywhere deployment.
"""
import sys

# Add your project directory to the path
path = '/home/YOUR_USERNAME/swapper'
if path not in sys.path:
    sys.path.insert(0, path)

# Import the Flask app from backtest_app
from backtest_app import app as application

# For PythonAnywhere, we use the 'application' variable
# Make sure to replace YOUR_USERNAME with your actual PythonAnywhere username
