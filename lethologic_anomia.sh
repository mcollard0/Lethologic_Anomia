#!/bin/bash

# Lethologic Anomia - Migration Service Runner
# This script makes it easy to run the migration service with the correct virtual environment

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if virtual environment exists
if [ ! -d "venv_new" ]; then
    echo -e "${RED}Error: Virtual environment 'venv_new' not found!${NC}"
    echo "Please run: python3 -m venv venv_new"
    echo "Then install dependencies: ./venv_new/bin/pip install -r requirements.txt"
    exit 1
fi

# Check if lethologic_anomia.py exists
if [ ! -f "lethologic_anomia.py" ]; then
    echo -e "${RED}Error: lethologic_anomia.py not found in current directory!${NC}"
    echo "Make sure you're running this script from the project root."
    exit 1
fi

echo -e "${GREEN}🏥 Lethologic Anomia - Medical Image Migration Service${NC}"
echo -e "${YELLOW}Using virtual environment: venv_new${NC}"
echo ""

# Activate virtual environment and run the program
source venv_new/bin/activate && python lethologic_anomia.py "$@"
