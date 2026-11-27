#!/usr/bin/env bash
#
# seed-dev.sh - Apply development seed data to the estancias database
#
# This script applies the dev-seed.sql file to populate the database with
# test data for development purposes. NEVER run this in production.
#
# Usage:
#   ./seed-dev.sh
#
# Prerequisites:
#   - Docker Compose services must be running (docker compose up -d)
#   - Database migrations must have been applied (happens automatically on first run)
#
# The seed data includes:
#   - 2 Directors
#   - 6 subsidiaries with 3-5 rooms each
#   - 15-20 employees per subsidiary (1 Manager, 1 Coordinator per room, rest are Employees)
#   - 2 schedules (Morning and Afternoon, Monday to Friday)
#   - All users share the password: Password123!
#
# The script is idempotent - safe to run multiple times. Existing data is not duplicated.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_FILE="${SCRIPT_DIR}/db/seeds/dev-seed.sql"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if docker compose is available
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: docker is not installed or not in PATH${NC}"
    exit 1
fi

# Check if the seed file exists
if [[ ! -f "$SEED_FILE" ]]; then
    echo -e "${RED}Error: Seed file not found at ${SEED_FILE}${NC}"
    exit 1
fi

# Check if docker-compose.yml exists
if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo -e "${RED}Error: docker-compose.yml not found at ${COMPOSE_FILE}${NC}"
    exit 1
fi

echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Estancias - Development Seed Data Loader            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if database container is running
echo -e "${YELLOW}Checking database container status...${NC}"
if ! docker compose -f "$COMPOSE_FILE" ps db | grep -q "Up"; then
    echo -e "${RED}Error: Database container is not running.${NC}"
    echo -e "${YELLOW}Start the services with: docker compose up -d${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Database container is running${NC}"
echo ""

# Check database connection
echo -e "${YELLOW}Testing database connection...${NC}"
if ! docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U estancias_user -d estancias &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to the database.${NC}"
    echo -e "${YELLOW}Wait for the database to be ready or check container logs: docker compose logs db${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Database connection successful${NC}"
echo ""

# Apply the seed data
echo -e "${YELLOW}Applying development seed data...${NC}"
echo -e "${BLUE}  File: ${SEED_FILE}${NC}"
echo ""

if docker compose -f "$COMPOSE_FILE" exec -T db psql -U estancias_user -d estancias < "$SEED_FILE"; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║            Seed data applied successfully!                 ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Database seeded with:${NC}"
    echo -e "  ${GREEN}•${NC} 2 Directors (can oversee all subsidiaries)"
    echo -e "  ${GREEN}•${NC} 6 Subsidiaries (Monterrey, Guadalajara, CDMX, Puebla, Querétaro, Mérida)"
    echo -e "  ${GREEN}•${NC} 3-5 Rooms per subsidiary"
    echo -e "  ${GREEN}•${NC} 15-20 Employees per subsidiary"
    echo -e "  ${GREEN}•${NC} 2 Schedules (Morning: 7am-2pm, Afternoon: 2pm-9pm)"
    echo ""
    echo -e "${YELLOW}Default credentials for all seeded users:${NC}"
    echo -e "  ${BLUE}Password:${NC} Password123!"
    echo ""
    echo -e "${YELLOW}Sample logins:${NC}"
    echo -e "  ${BLUE}Directors:${NC}"
    echo -e "    • director1@seed.example.com"
    echo -e "    • director2@seed.example.com"
    echo -e "  ${BLUE}Managers:${NC}"
    echo -e "    • encargado.1@seed.example.com (Monterrey)"
    echo -e "    • encargado.2@seed.example.com (Guadalajara)"
    echo -e "  ${BLUE}Coordinators:${NC}"
    echo -e "    • coordinador.1.1@seed.example.com (Monterrey, Sala 1)"
    echo -e "    • coordinador.2.1@seed.example.com (Guadalajara, Sala 1)"
    echo ""
    echo -e "${GREEN}✓ Ready for development and testing!${NC}"
    echo ""
else
    echo ""
    echo -e "${RED}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║              Error applying seed data!                     ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Troubleshooting:${NC}"
    echo -e "  1. Check database logs: ${BLUE}docker compose logs db${NC}"
    echo -e "  2. Verify migrations ran: ${BLUE}docker compose logs db | grep migration${NC}"
    echo -e "  3. Restart services: ${BLUE}docker compose restart${NC}"
    echo ""
    exit 1
fi
