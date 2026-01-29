#!/bin/bash
# Start the agent-control server with DeepEval evaluator registered

# Get the directory containing this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Add this directory to PYTHONPATH so the server can import the evaluator
export PYTHONPATH="$DIR:$PYTHONPATH"

# Import the evaluator before starting the server
python3 -c "import sys; sys.path.insert(0, '$DIR'); from evaluator import DeepEvalEvaluator; print(f'✓ Loaded {DeepEvalEvaluator.metadata.name}')"

echo "Starting server with DeepEval evaluator..."
echo "PYTHONPATH: $PYTHONPATH"
echo ""

# Navigate to repository root and start server
cd "$DIR/../.."
./demo.sh start
