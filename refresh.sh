#!/bin/bash
# Re-download one session (default: the current one) and rebuild every session page in site/.
# Past sessions don't change, so only the current one normally needs re-downloading.
# Usage: ./refresh.sh [session_year]
set -e
cd "$(dirname "$0")"
python3 fetch_bills.py "${1:-2025}"
python3 build_data.py
