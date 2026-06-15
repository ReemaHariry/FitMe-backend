#!/bin/bash
# Quick start script for Mac/Linux
# Run with: bash start_server.sh

echo "========================================"
echo "AI Fitness Trainer API - Starting..."
echo "========================================"
echo ""

# Activate virtual environment
source venv/bin/activate

# Start the server
echo "Starting FastAPI server on http://localhost:8000"
echo "Press CTRL+C to stop the server"
echo ""
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
