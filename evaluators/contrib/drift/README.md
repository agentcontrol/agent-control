# agent-control-evaluator-drift

Temporal behavioral drift evaluator for [Agent Control](https://github.com/agentcontrol/agent-control).

Detects gradual behavioral degradation patterns that point-in-time evaluators miss.

## The Problem

Agent Control's built-in evaluators (regex, list, SQL, JSON) assess individual interactions. They answer: *"Is this response safe right now?"* They don't answer: *"Is this agent becoming less reliable over time?"*

Empirical observation from [published longitudinal research](https://doi.org/10.5281/zenodo.19028012) across LLM agents:

- Agents scoring 1.0 on point-in-time tests showed measurable drift over 28-day windows
- Degradation was **non-monotonic**: stability windows followed by abrupt shifts, not gradual decline
- Regression signals were noisy below 5 observations; rolling windows of ≥5 gave actionable signal
- Two production deployments confirmed the same pattern independently

This evaluator fills that gap by tracking behavioral scores over time and flagging when recent performance diverges from an established baseline.

## How It Works

```
Single run:  regex/list evaluators → pass/fail per message
Drift eval:  records score over N runs → alerts when recent window < baseline
```

The evaluator:
1. Records a numeric score (0.0–1.0) for each evaluation
2. Compares the recent window (last N observations) against a baseline (first M observations)
3. Returns `matched=True` (drift detected) when the gap exceeds the configured threshold
4. Stores history in a local JSON file (no external dependencies required)

## Installation

```bash
pip install agent-control-evaluator-drift
```

Or with `uv`:
```bash
uv add agent-control-evaluator-drift
```

## Usage

### Basic Configuration

```python
from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

config = DriftEvaluatorConfig(
    agent_id="sales-agent-prod",       # Track this agent separately
    storage_path="/tmp/drift-history", # Where to persist observations
    window_size=10,                    # Recent window: last 10 scores
    baseline_size=20,                  # Baseline: first 20 scores
    drift_threshold=0.10,              # Alert if recent avg drops >10% vs baseline
)

evaluator = DriftEvaluator(config)

# Each call records the score and checks for drift
result = await evaluator.evaluate(0.85)  # Score from your primary evaluator
```

### In Agent Control YAML

```yaml
controls:
  - name: "drift-check"
    evaluator: "drift.temporal"
    config:
      agent_id: "my-agent"
      storage_path: "/var/lib/agent-control/drift"
      window_size: 10
      baseline_size: 20
      drift_threshold: 0.10
    action: alert  # or block
```

### Chaining with Other Evaluators

The drift evaluator expects a numeric score (0.0–1.0) as input. Pair it with a selector that extracts a confidence or quality score from agent output:

```yaml
controls:
  - name: "quality-score"
    selector: "$.quality_score"      # Extract score from agent output
    evaluator: "drift.temporal"
    config:
      agent_id: "customer-support"
      drift_threshold: 0.15
```

## Configuration Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `agent_id` | `str` | `"default"` | Identifier to track agents separately |
| `storage_path` | `str` | `/tmp/drift-history` | Directory for history files |
| `window_size` | `int` | `10` | Number of recent observations to compare |
| `baseline_size` | `int` | `20` | Number of initial observations to establish baseline |
| `drift_threshold` | `float` | `0.10` | Minimum score drop to trigger drift alert (0.0–1.0) |
| `min_observations` | `int` | `5` | Minimum observations before drift detection activates |
| `on_error` | `str` | `"allow"` | Action on storage error: `"allow"` or `"deny"` |

## Output

`EvaluatorResult` fields:

- `matched`: `True` when drift detected (recent window below baseline by threshold)
- `confidence`: `1.0` when drift detected, `0.0` otherwise
- `message`: Human-readable status (e.g., "Drift detected: baseline 0.92 → recent 0.78")
- `metadata`:
  - `agent_id`: Agent being tracked
  - `observation_count`: Total observations recorded
  - `baseline_avg`: Average score during baseline period
  - `recent_avg`: Average score in recent window
  - `drift_magnitude`: How far recent dropped below baseline
  - `status`: `"drift_detected"`, `"stable"`, `"baseline_building"`, or `"insufficient_data"`

## Research Background

This evaluator is based on empirical findings from [PDR: Probabilistic Drift Rate for Longitudinal Behavioral Reliability in LLM-based Agents](https://doi.org/10.5281/zenodo.19028012).

Key findings that shaped the design:
- **Window ≥ 5**: Drift signals become reliable only above 5 observations (noisy below)
- **Non-monotonic patterns**: Degradation isn't gradual; agents can return to baseline without intervention
- **Specification matters**: Ambiguous task specs cause variance that looks like drift — scope `agent_id` to well-defined tasks
- **Independent replication**: NexusGuard production deployment confirmed the same windowed-scoring behavior

## License

Apache 2.0
