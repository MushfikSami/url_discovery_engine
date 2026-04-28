#!/bin/bash

# ==========================================
# CRAWLER FLEET CONFIGURATION
# ==========================================
# Set the number of concurrent workers you want to run
NUM_WORKERS=30 

# Create a directory for the logs if it doesn't exist
mkdir -p crawler_logs

echo "🚀 Launching Spider Fleet with $NUM_WORKERS workers..."

# Loop to start the workers
for i in $(seq 1 $NUM_WORKERS)
do
    # Launch in background with nohup, redirecting output to individual log files
    nohup python spider.py > "crawler_logs/worker_$i.log" 2>&1 &
    
    # Get the Process ID (PID) of the last launched background job
    PID=$!
    echo "  -> Started Worker $i (PID: $PID)"
    
    # Small delay so they don't all hit the database at the exact same millisecond
    sleep 0.5
done

echo ""
echo "[+] Fleet launched successfully!"
echo "    Monitor logs in the ./crawler_logs/ directory."
echo "    Example: tail -f crawler_logs/worker_1.log"
