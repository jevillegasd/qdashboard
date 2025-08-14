#!/bin/bash

# QDashboard Startup Script
# This script starts the Quantum Computing Dashboard
#
# QDashboard file management is built on flask-file-server by Wildog
# https://github.com/Wildog/flask-file-server
# Extended with quantum computing specific features

#Only for Juan Villegas - delete after testing
#source ~/.env/qwork2/bin/activate
#export QIBOLAB_PLATFORMS=~/.repo/qibolab_platforms_qrc


echo "Starting QDashboard..."
echo "========================================"
echo "QDashboard - Quantum Computing Dashboard"
echo ""
echo "========================================"

export QD_FILE_PATH="$(dirname "$(realpath "$0")")"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check if required packages from the requirements.txt are installed
if [ ! -f "$QD_FILE_PATH/requirements.txt" ]; then
    echo "Error: requirements.txt not found. Please ensure you are in the correct directory."
    exit 1
else
    echo "Note: Skipping pip install to avoid environment changes."
    echo "If you need to install requirements, run: pip3 install -r requirements.txt"
fi
# python3 -c "import flask, humanize, yaml" 2>/dev/null || {
#     echo "Installing required dependencies..."
#     pip3 install flask humanize pathlib2 werkzeug PyYAML
# }

#if no environment is activated, activate the virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Activating virtual environment..."
    source "$QD_FILE_PATH/venv/bin/activate"
fi

# Set default environment variables if not set
export QD_BIND=${QD_BIND:-"127.0.0.1"}
export QD_PORT=${QD_PORT:-"5005"}
export QD_PATH=${QD_PATH:-"$HOME"}

#If QIBOLAB_PLATFORMS is not set, use the default path
if [ -z "$QIBOLAB_PLATFORMS" ]; then
    export QIBOLAB_PLATFORMS="$QD_PATH/qibolab_platforms_qrc"
fi

echo "Configuration:"
echo "  Bind Address: $QD_BIND"
echo "  Port: $QD_PORT"
echo "  Root Path: $QD_PATH"
echo "  Platforms Path: $QIBOLAB_PLATFORMS"
echo "  Python Path: $(which python3)"
echo "  Process ID: $$"
echo ""
echo "Starting server..."
echo "Access the dashboard at: http://$QD_BIND:$QD_PORT"
echo ""

# Start the dashboard from the current file path
dashboard_file_path="$QD_FILE_PATH/app.py"
if [ ! -f "$dashboard_file_path" ]; then
    echo "Error: Dashboard file not found at $dashboard_file_path"
    exit 1
fi

# Use exec to replace the shell process with Python to avoid signal handling issues
# exec python "$dashboard_file_path"
python "$dashboard_file_path"