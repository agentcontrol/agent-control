# galileo.llm — LLM-as-Judge Evaluator

This guide covers testing Agent Control with the `galileo.llm` (LLM-as-judge) evaluator for custom LLM-based evaluation logic — for example, detecting PII in outputs or scoring whether a user's goal was advanced.

---

## Step 1 — Create a DevStack

1. Visit [https://aegis.platform.galileo.ai](https://aegis.platform.galileo.ai)
2. Go to **DevStacks** and click **+ Create Stack**
3. Fill in the form:
   - **Cloud Provider**: Google Cloud (GCP)
   - **Stack Preset**: Wizard (GPU)
   - **Capacity**: S
   - **Pinned Infra Branch**: `main`
   - **Override Profile**: select `scorer-invoke-runtime (gcp)`

     > This override enables the new runtime path for both Luna and LLM-as-judge
     > evaluators and adds the `galileo.llm` evaluator. It sets two feature flags:
     > - `GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME=enabled` — required for Luna
     > - `GALILEO_FEATURE_FLAG_LLM_EVALUATOR=enabled` — additionally required for LLM

   - **Stack Name**: choose a name, e.g. `test-agent-control`
   - **Duration (hours)**: `24`
   - **Helm Branch**: `release`

4. Click **Create Stack** and wait for the stack status to become **RUNNING**

> For access to Aegis or help with devstack creation, contact **Shuai** (shuais@cisco.com) or **Yixin** (yixint@cisco.com).
> More details: [Galileo Dev Stacks wiki](https://splunk.atlassian.net/wiki/spaces/Galileo/pages/1080199938954/Galileo+Dev+Stacks)
> and [github.com/rungalileo/aegis](https://github.com/rungalileo/aegis)

---

## Step 2 — Configure LLM Evaluators in the Galileo Console

Open the Galileo Console for your devstack (click **Open** next to your stack
in Aegis) and navigate to **Evaluators**.

Preset/out-of-the-box evaluators are available but cannot be used directly.
You must **duplicate** them and configure the copy.

### Output PII evaluator

1. Find **Output PII** in the Evaluators list and click **Duplicate**
2. Configure the duplicate:
   - **Name**: `Output PII` (or a name of your choice)
   - **Apply to**: `Trace`
   - **Input style**: `Trace output only`
   - **LLM model**: select the model from the dropdown
   - **No of judges**: `1`
   - **Step-by-step reasoning**: on
   - **Output type**: `Percentage`
   - **Roll-up**: `AVG`
   - **Thresholds**: green `>= 50%`, red `<= 0%`
3. Save the evaluator.

### Action Advancement evaluator

1. Find **Action Advancement** in the Evaluators list and click **Duplicate**
2. Configure the duplicate:
   - **Name**: `Action Advancement` (or a name of your choice)
   - **Apply to**: `Trace`
   - **Input style**: `Trace output only`
   - **LLM model**: select the model from the dropdown
   - **No of judges**: `1`
   - **Step-by-step reasoning**: off
   - **Output type**: `Percentage`
   - **Roll-up**: `AVG`
   - **Thresholds**: green `>= 50%`, red `<= 0%`
   - **Prompt**: `Return 1 if the output contains the phrase "Please try again later", otherwise return 0.`
3. Save the evaluator.

---

## Step 3 — Create Controls in the Galileo Console

Open the Galileo Console for your devstack (click **Open** next to your stack
in Aegis).

Create the two controls for the travel assistant demo. Refer to
[`travel_assistant_controls.json`](https://github.com/namrataghadi-galileo/ace-demo/blob/main/travel_assistant_controls.json)
for the full field reference.

Controls can be created and attached in two ways:
   - **From the Controls store**: click the **Controls** icon in the left bar,
     create the control globally, then open your agent stream, go to the
     **Controls** tab, click **Add Controls**, and add both controls.
   - **From within the agent stream**: open your agent stream, go to the
     **Controls** tab, and create the controls directly there — they will be
     automatically attached to the stream.

1. Create the following two controls using the values from
   `travel_assistant_controls.json` as the field reference:

   **`travel-assistant-deny-trace-output-pii`**
   - Control name: `travel-assistant-deny-trace-output-pii`
   - Description: `Deny a trace whose final travel assistant response leaks PII`
   - Stages: `POST (after execution)`
   - Action: `Deny`
   - Execution environment: `Server`
   - Step types: `Trace`
   - Evaluator type: `llm`
   - Path: `output`
   - Evaluator: select **Output PII** from the scorer dropdown
   - Comparison value: `0.5`
   - Operator: `gte`
   - Payload Field: leave unset
   - Timeout Ms: `30000`

   **`travel-assistant-steer-trace-action-not-advanced`**
   - Control name: `travel-assistant-steer-trace-action-not-advanced`
   - Description: `Steer a trace when the agent failed to advance the user's travel goal`
   - Stages: `POST (after execution)`
   - Action: `Steer`
   - Steering context: leave empty
   - Execution environment: `Server`
   - Step types: `Trace`
   - Evaluator type: `llm`
   - Path: `output`
   - Evaluator: select **Action Advancement** from the scorer dropdown
   - Comparison value: `1`
   - Operator: `eq`
   - Payload Field: `output`
   - Timeout Ms: `30000`

---

## Step 4 — Export Environment Variables

```bash
export GALILEO_CONSOLE_URL=https://console-<your-devstack-name>.gcp-dev.galileo.ai
export GALILEO_API_URL=https://api-<your-devstack-name>.gcp-dev.galileo.ai
export AGENT_CONTROL_URL=https://console-<your-devstack-name>.gcp-dev.galileo.ai/api/agent-control
export AGENT_CONTROL_AGENT_NAME=<your-agent-name>
export GALILEO_PROJECT=<your-project-name>
export GALILEO_LOG_STREAM=<your-agent-stream-name>
export GALILEO_API_KEY=<your-galileo-api-key>

```

---

## Step 5 — Install ace-demo and Run the App

Clone the [ace-demo](https://github.com/namrataghadi-galileo/ace-demo) repo
and install dependencies:

```bash
git clone https://github.com/namrataghadi-galileo/ace-demo
cd ace-demo
python3.12 -m venv .venv
source .venv/bin/activate
pip install .
```

Run the travel assistant app:

```bash
streamlit run travel_assistant_multi_trace_streamlit_app.py
```

Open your browser at `http://localhost:8501`.

The app runs two scenarios:

| Scenario | What happens | Expected outcome |
|---|---|---|
| **Scenario A** | Flight-booking LLM leaks PII in output | **Denied** — Output PII control fires |
| **Scenario B** | Flight LLM returns a bad result for `book_flights` | **Steered** — Action Advancement control fires, app retries with alternate flight booking |

---

## Troubleshooting

**`galileo.llm evaluator is not available`**
→ The devstack was not created with the `scorer-invoke-runtime (gcp)` override
profile. Both `GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME` and
`GALILEO_FEATURE_FLAG_LLM_EVALUATOR` must be enabled on the AC server.

**`Authenticated execution metadata is missing organization_id`**
→ The API key is invalid or the `Galileo-API-Key` header is not being used.
Verify `GALILEO_API_KEY` is set correctly.

**Controls not firing**
→ Confirm both controls are created, enabled, and bound to your agent stream in
the Console.
