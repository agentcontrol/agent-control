# galileo.luna — Luna Evaluator

This guide covers testing Agent Control with the `galileo.luna` (SLM-as-judge) evaluator across multiple step types — trace, session, LLM, tool, and retriever.

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

     > This override enables the new runtime path for Luna evaluators. It sets
     > the feature flag `GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME=enabled`
     > which is required for `galileo.luna`.

   - **Stack Name**: choose a name, e.g. `test-agent-control`
   - **Duration (hours)**: `24`
   - **Helm Branch**: `release`

4. Click **Create Stack** and wait for the stack status to become **RUNNING**

> For access to Aegis or help with devstack creation, contact **Shuai** (shuais@cisco.com) or **Yixin** (yixint@cisco.com).
> More details: [Galileo Dev Stacks wiki](https://splunk.atlassian.net/wiki/spaces/Galileo/pages/1080199938954/Galileo+Dev+Stacks)
> and [github.com/rungalileo/aegis](https://github.com/rungalileo/aegis)

---

## Step 2 — Configure Luna Evaluators in the Galileo Console

Open the Galileo Console for your devstack (click **Open** next to your stack
in Aegis) and navigate to **Evaluators**.

Preset/out-of-the-box evaluators are available but cannot be used directly.
You must **duplicate** them and configure the copy.

Duplicate and configure the following five Luna evaluators:

### Output PII
- **Apply to**: `Trace`
- **Input style**: `Trace output only`

### Action Completion
- **Apply to**: `Session`
- **Input style**: `Session output only`

### Tool Selection Quality
- **Apply to**: `LLM`
- **Input style**: `LLM output only`

### Tool Error Rate
- **Apply to**: `Tool`
- **Input style**: `Tool output only`

### Chunk Relevance
- **Apply to**: `Retriever`
- **Input style**: `Retriever output only`

Save each evaluator after configuring it.

---

## Step 3 — Create Controls in the Galileo Console

Create the five controls for the banking multilevel demo. Refer to
[`banking_multilevel_controls.json`](https://github.com/namrataghadi-galileo/ace-demo/blob/main/banking_multilevel_controls.json)
for the full field reference.

Controls can be created and attached in two ways:
   - **From the Controls store**: click the **Controls** icon in the left bar,
     create the control globally, then open your agent stream, go to the
     **Controls** tab, click **Add Controls**, and add all controls.
   - **From within the agent stream**: open your agent stream, go to the
     **Controls** tab, and create the controls directly there — they will be
     automatically attached to the stream.

1. Create the following five controls using the values from
   `banking_multilevel_controls.json` as the field reference:

   **`banking-multilevel-deny-trace-sensitive-final`**
   - Description: `Deny a trace whose final banking response contains sensitive customer data.`
   - Stages: `POST (after execution)`
   - Action: `Deny`
   - Execution environment: `Server`
   - Step types: `Trace`
   - Step name regex: `^banking_multilevel_trace_sensitive_final$`
   - Evaluator type: `luna`
   - Path: `*`
   - Evaluator: select **Output PII** from the scorer dropdown
   - Operator: `contains`, Threshold: `email`

   **`banking-multilevel-deny-session-repeated-bypass`**
   - Description: `Deny a session that repeatedly bypasses approval and reports action completion.`
   - Stages: `POST (after execution)`
   - Action: `Deny`
   - Execution environment: `SDK`
   - Step types: `Session`
   - Step name regex: `^banking_multilevel_session_repeated_bypass$`
   - Evaluator type: `luna`
   - Path: `*`
   - Evaluator: select **Action Completion** from the scorer dropdown
   - Operator: `gte`, Threshold: `0.5`

   **`banking-multilevel-deny-llm-sensitive-reply`**
   - Description: `Deny an LLM step that selects account closure instead of transfer planning.`
   - Stages: `POST (after execution)`
   - Action: `Deny`
   - Execution environment: `Server`
   - Step types: `LLM`
   - Step name regex: `^banking_multilevel_llm_bad_tool_selection$`
   - Evaluator type: `luna`
   - Path: `*`
   - Evaluator: select **Tool Selection Quality** from the scorer dropdown
   - Operator: `lt`, Threshold: `0.5`

   **`banking-multilevel-deny-tool-transfer-error`**
   - Description: `Deny a tool step whose sandbox transfer function returns an error.`
   - Stages: `POST (after execution)`
   - Action: `Deny`
   - Execution environment: `SDK`
   - Step types: `Tool`
   - Step name regex: `^banking_multilevel_tool_transfer_error$`
   - Evaluator type: `luna`
   - Path: `*`
   - Evaluator: select **Tool Error Rate** from the scorer dropdown
   - Operator: `gte`, Threshold: `0.5`

   **`banking-multilevel-deny-retriever-irrelevant-policy`**
   - Description: `Deny a retriever step when any returned policy chunk is irrelevant.`
   - Stages: `POST (after execution)`
   - Action: `Deny`
   - Execution environment: `SDK`
   - Step types: `Retriever`
   - Step name regex: `^banking_multilevel_retriever_irrelevant_policy$`
   - Evaluator type: `luna`
   - Path: `*`
   - Evaluator: select **Chunk Relevance** from the scorer dropdown
   - Operator: `contains`, Threshold: `false`

---

## Step 4 — Export Environment Variables

```bash
export GALILEO_CONSOLE_URL=https://console-<your-devstack-name>.gcp-dev.galileo.ai
export GALILEO_API_URL=https://api-<your-devstack-name>.gcp-dev.galileo.ai
export AGENT_CONTROL_URL=https://console-<your-devstack-name>.gcp-dev.galileo.ai/api/agent-control
export AGENT_CONTROL_AGENT_NAME=banking-multilevel-runtime-demo
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

Run the banking multilevel app:

```bash
streamlit run banking_multilevel_streamlit_app.py
```

Open your browser at `http://localhost:8501`.

The app runs five scenarios, one per step type:

| Scenario | Step type | Control | Expected outcome |
|---|---|---|---|
| Trace leaks PII | Trace | `banking-multilevel-deny-trace-sensitive-final` | **Denied** |
| Session bypasses approval | Session | `banking-multilevel-deny-session-repeated-bypass` | **Denied** |
| LLM selects wrong tool | LLM | `banking-multilevel-deny-llm-sensitive-reply` | **Denied** |
| Tool transfer error | Tool | `banking-multilevel-deny-tool-transfer-error` | **Denied** |
| Retriever returns irrelevant chunk | Retriever | `banking-multilevel-deny-retriever-irrelevant-policy` | **Denied** |

---

## Troubleshooting

**`galileo.luna evaluator is not available`**
→ The devstack was not created with the `scorer-invoke-runtime (gcp)` override
profile. `GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME` must be enabled on the
AC server.

**`Authenticated execution metadata is missing organization_id`**
→ The API key is invalid or the `Galileo-API-Key` header is not being used.
Verify `GALILEO_API_KEY` is set correctly.

**Controls not firing**
→ Confirm all five controls are created, enabled, and bound to your agent
stream in the Console. Also confirm the step name regex matches the step name
used in the app.
