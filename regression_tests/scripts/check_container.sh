# List of containers to check
CONTAINERS=("agent-1" "agent-2" "agent-3"  "agent-4" "controller" "portal")

HAS_ERROR=0
for CONTAINER in "${CONTAINERS[@]}"; do
    echo "🔍 Checking $CONTAINER..."

    CONTAINER_ID=$(docker compose  -f regression_tests/docker-compose.yml ps -q "$CONTAINER")

    if [ -z "$CONTAINER_ID" ]; then
        echo "❌ Container $CONTAINER not found."
        HAS_ERROR=1
        continue
    fi

    # Get container exit code
    EXITED=$(docker inspect -f '{{.State.ExitCode}}' "$CONTAINER_ID")

    # Get container logs
    LOGS=$(docker compose -f regression_tests/docker-compose.yml logs "$CONTAINER")

    # Search for error keywords (added Errno)
    if echo "$LOGS" | grep -q -E "FileNotFoundError|Traceback|ERROR|Errno"; then
        echo "❌ Error detected in logs for $CONTAINER"
        echo "----------------------------------------"
        echo "$LOGS" | grep -E "FileNotFoundError|Traceback|ERROR|Errno"
        echo "----------------------------------------"
        echo "------ Full Logs for $CONTAINER (might be cut as it too long)------"
        echo "$LOGS"
        HAS_ERROR=1
    fi
    # Always print controller and agent logs for visibility
    if [[ "$CONTAINER" = "controller" || "$CONTAINER" = "agent-*" ]]; then
        echo "------ Logs for $CONTAINER ------"
        echo "$LOGS"
        echo "---------------------------------"
    fi
done

if [ "$HAS_ERROR" -eq 1 ]; then
    echo "❌ One or more containers had errors."
    exit 1
else
    echo "✅ All containers are healthy and logs are clean."
    exit 0
fi

