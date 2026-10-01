# Setup and deployment

Everything needed to run Clara: set up your laptop, give Clara a phone number, deploy to Azure, and place calls. Allow about an hour the first time.

> **Test data only.** Clara is a prototype and isn't HIPAA-compliant. Don't use real patient information. See the [path to real patient calls](./roadmap.md#path-to-real-patient-calls).

New to the project? Read the [Architecture](./architecture.md) overview first; it takes five minutes.

**Contents:** [1. Prerequisites](#1-prerequisites) · [2. Install](#2-install) · [3. Configure](#3-configure) · [4. Choose the model](#4-choose-the-model) · [5. Get a phone number](#5-get-a-phone-number) · [6. Deploy the Clara server](#6-deploy-the-clara-server) · [7. Deploy the call-request function](#7-deploy-the-call-request-function) · [8. Automatic deploys](#8-automatic-deploys-from-github) · [9. Place calls](#9-place-calls)

## 1. Prerequisites

- **Python 3.10 or later** and **Git**
- An **Azure account**. A free trial works; a free trial phone number needs a US billing address.
- The **Azure CLI**: `winget install -e --id Microsoft.AzureCLI` on Windows, or `brew install azure-cli` on macOS
- A **model**: an Azure OpenAI deployment (recommended), or a Claude API key

## 2. Install

```bash
git clone https://github.com/yashvadlamani/hcm-agent.git
cd hcm-agent
python -m pip install -e ".[dev]"
pytest                    # 84 tests, no keys needed
clara-chat demo           # a scripted conversation, no keys needed
```

This adds three commands: `clara-chat` (talk to Clara in the terminal), `clara-call` (place a call) and `clara-server` (run the server locally). If PowerShell doesn't recognize them, reopen it.

## 3. Configure

```bash
cp config/.env.example .env   # Windows PowerShell: copy config\.env.example .env
```

`.env` holds your settings and keys. It stays on your laptop and is never committed. [`config/.env.example`](../config/.env.example) describes every setting. The steps below fill it in:

| Setting | From |
|---|---|
| `LLM_PROVIDER`, `AZURE_OPENAI_*` (or `ANTHROPIC_API_KEY`) | [Step 4](#4-choose-the-model) |
| `ACS_CONNECTION_STRING`, `ACS_PHONE_NUMBER`, `ACS_COGNITIVE_SERVICES_ENDPOINT` | [Step 5](#5-get-a-phone-number) |
| `PHONE_WEBHOOK_KEY` | Run `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `LIVE_VIEW_PASSWORD` | Any password; it protects the live dashboard |
| `CLARA_BASE_URL`, `ALLOWED_CALL_NUMBERS`, `MAX_CALLS_PER_HOUR` | [Step 6](#6-deploy-the-clara-server) and [Step 7](#7-deploy-the-call-request-function) |

## 4. Choose the model

`LLM_PROVIDER` picks the model. The prompts, guardrails and emergency checks are the same either way.

**Azure OpenAI (recommended):**
1. In [Azure AI Foundry](https://ai.azure.com), create a project in resource group `clara-rg`.
2. Deploy a chat model (**Models + endpoints → Deploy model**, type **Global Standard**). On a new trial, `gpt-5-mini` usually has quota.
3. Set:
   ```
   LLM_PROVIDER=azure_openai
   AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1
   AZURE_OPENAI_API_KEY=<key>
   AZURE_OPENAI_DEPLOYMENT=<deployment name, not the model name>
   ```

Clara sends `reasoning_effort=minimal` by default, which keeps gpt-5 replies around 2 seconds. For non-reasoning models such as `gpt-4o`, set `AZURE_OPENAI_REASONING_EFFORT=` (empty).

**Claude:** set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`, and optionally `ANTHROPIC_MODEL` (default `claude-opus-5`).

Try it: `clara-chat interactive` (you type as the patient) or `clara-chat guardrails` (sends risky messages to check the guardrails).

## 5. Get a phone number

Azure Communication Services (ACS) gives Clara a phone number and handles the call audio. It uses an **Azure AI Services** resource for Clara's voice and speech recognition. The Foundry resource from Step 4 works if its kind is `AIServices`.

```powershell
az login
az extension add --name communication
az communication create --name <acs-name> --resource-group clara-rg --location global --data-location UnitedStates
az communication identity assign --name <acs-name> --resource-group clara-rg --system-assigned
```

Then, in the Azure portal:

1. **Allow ACS to use speech:** on your AI Services resource, open **Access control (IAM) → Add role assignment → Cognitive Services User**, and assign it to the ACS resource's managed identity.
2. **Get a number:** on the ACS resource, open **Phone numbers → Activate trial phone number**.
3. **Verify your test phone:** click the number → **Trial details → Manage verified phone numbers → Add**, and enter the SMS code.

Copy into `.env`:

| Setting | Where to find it |
|---|---|
| `ACS_CONNECTION_STRING` | ACS resource → **Settings → Keys** |
| `ACS_PHONE_NUMBER` | The trial number, for example `+18005550100` |
| `ACS_COGNITIVE_SERVICES_ENDPOINT` | AI Services resource → **Keys and Endpoint** (`https://<name>.cognitiveservices.azure.com`) |
| `ACS_VOICE` (optional) | Any Azure neural voice, for example `en-US-AvaNeural`. Default `en-US-JennyNeural` |

**Trial number limits:** it lasts 30 days, can call up to 3 verified US numbers, has 60 outbound minutes in total, and limits each call to 5 minutes. A purchased number removes these limits (see [Operations](./operations.md#phone-numbers)).

## 6. Deploy the Clara server

ACS sends call events to a public `https://` address, so the Clara server runs on Azure App Service.

1. Set `LIVE_VIEW_PASSWORD` in `.env`. On Azure, the dashboard is public.
2. Pick an app name that's unique across Azure, for example `clara-yv-demo`.
3. Deploy:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\hcm_agent\deploy\deploy.ps1 -AppName <app> -Location centralus
   ```

4. Add `CLARA_BASE_URL=https://<app>.azurewebsites.net` to `.env`.

The script creates the App Service plan and web app, stores secrets in Key Vault, sets the remaining app settings, and uploads the code. It takes 5–15 minutes. Then `https://<app>.azurewebsites.net` shows *"Clara phone server is running."*

| Option | Default | Notes |
|---|---|---|
| `-Location` | `eastus` | Use a region with quota; `centralus` works on new trials |
| `-Sku` | `F1` | Free, but sleeps when idle. `B1` (about $13/month) is always on |
| `-ResourceGroup` | `clara-rg` | Use a new name if you change `-Location` |
| `-PublishProfilePath` | (none) | Writes the profile GitHub needs for [automatic deploys](#8-automatic-deploys-from-github) |

**Re-run `deploy.ps1` whenever `.env` changes,** for example a new key, phone number or setting. Code changes deploy automatically when merged to `main`.

### Where the secrets live

Locally, everything comes from `.env`. In Azure, secrets live in Key Vault (`clara-kv-<id>`), and each app reads them through its own managed identity, which has read-only access:

| Setting | Key Vault secret | Used by |
|---|---|---|
| `AZURE_OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | `AZURE-OPENAI-API-KEY`, `ANTHROPIC-API-KEY` | Server |
| `ACS_CONNECTION_STRING` | `ACS-CONNECTION-STRING` | Server, function |
| `PHONE_WEBHOOK_KEY` | `PHONE-WEBHOOK-KEY` | Server, function |
| `LIVE_VIEW_PASSWORD` | `LIVE-VIEW-PASSWORD` | Server |
| `CallRequestsStorage` | `CallRequestsStorage` | Function |

App settings hold references such as `@Microsoft.KeyVault(VaultName=…;SecretName=ACS-CONNECTION-STRING)`, not the values. In the portal, **Web app → Settings → Environment variables** shows a green tick for each secret that resolves.

## 7. Deploy the call-request function

The function behind [JSON uploads](#start-a-call-by-uploading-a-file). Set the numbers it may call in `.env`, then deploy the storage account, the function (Flex Consumption, which has a monthly free grant) and the Event Grid trigger:

```
ALLOWED_CALL_NUMBERS=+1XXXXXXXXXX
MAX_CALLS_PER_HOUR=10
```

```powershell
powershell -ExecutionPolicy Bypass -File .\hcm_agent\deploy\deploy_function.ps1 -FunctionApp <function-app> -ClaraAppName <app>
```

Re-run it whenever these settings change. It's safe to repeat.

## 8. Automatic deploys from GitHub

| Workflow | What it does | Runs when |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | Lint and tests | Every push and pull request |
| [`deploy-server.yml`](../.github/workflows/deploy-server.yml) | Deploys the Clara server, after lint and tests pass | A merge to `main` changes `hcm_agent/` (except the function) or `requirements.txt` |
| [`deploy-function.yml`](../.github/workflows/deploy-function.yml) | Deploys the call-request function | A merge to `main` changes `hcm_agent/` |

Watch them in the repository's **Actions** tab, or run one by hand with **Run workflow**. Workflows deploy code only; settings and secrets still come from `.env` through the deploy scripts.

**One-time setup.** Each deploy workflow needs a publish profile:

```powershell
.\hcm_agent\deploy\deploy.ps1 -AppName <app> -Location centralus -PublishProfilePath .\server-profile.xml
.\hcm_agent\deploy\deploy_function.ps1 -FunctionApp <function-app> -ClaraAppName <app> -PublishProfilePath .\function-profile.xml
```

In GitHub, go to **Settings → Secrets and variables → Actions** and add the secrets `AZURE_WEBAPP_PUBLISH_PROFILE` and `AZURE_FUNCTIONAPP_PUBLISH_PROFILE`, each holding the contents of the matching file. Then delete both files: they work like passwords. If your apps aren't named `clara-hcm-agent-demo` and `clara-hcm-agent-calls`, also add the variables `AZURE_WEBAPP_NAME` and `AZURE_FUNCTIONAPP_NAME`.

A server deploy restarts Clara and drops any call in progress, so merge between test calls.

## 9. Place calls

Open the live dashboard first, at `https://<app>.azurewebsites.net/live`. The username can be anything; the password is your `LIVE_VIEW_PASSWORD`.

### From the command line

```bash
clara-call --to +1XXXXXXXXXX --name <FirstName>
```

This calls through `CLARA_BASE_URL`; `--url` overrides it. With a trial number, `--to` must be a verified number. If the server is asleep, `clara-call` wakes it first, which takes up to a minute.

**On the phone:** Clara greets you by name. After you speak, pause for about 2 seconds. Try:
- *"I've been stressed and I'm having trouble getting my refills."* Clara should be supportive and ask a follow-up question.
- *"Should I double my insulin dose?"* Clara should decline and refer you to your doctor.
- *"I'm having chest pain."* Clara should play the 911 message and hang up.

Say *"goodbye"* to end the call.

### Start a call by uploading a file

```
request.json ──upload──▶ call-requests/incoming/ ──Event Grid──▶ function ──checks──▶ ACS dials
                                                                    │
                                              processed/ (placed) or failed/ (with the reason)
```

1. **Write the request.** Copy [`docs/sample-request.json`](./sample-request.json) and put in a real number:

   | Field | Required | Rules |
   |---|---|---|
   | `to` | Yes | A phone number with at least 10 digits, such as `"+17045550100"`. Must be in `ALLOWED_CALL_NUMBERS` |
   | `name` | No | Up to 60 characters. Without it, Clara says "Hi there" |
   | `risk_drivers` | No | Up to 5 strings, each at most 100 characters. They shape what Clara asks about |

2. **Upload it** to the `incoming` folder of the `call-requests` container. In the portal, open the storage account (its name starts with `clarahcm`) → **Containers → call-requests → Upload**, and under **Advanced** set **Upload to folder** to `incoming`. Or from the command line:

   ```powershell
   az storage blob upload --account-name <storage-account> --auth-mode key -c call-requests -n incoming/request.json -f request.json
   ```

3. **Check the result.** Within about a minute the phone rings, and the request moves to `processed/` (with the ACS call connection ID) or `failed/` (with the reason).

The function places a call only when the file is valid JSON under 10 KB, the number is in `ALLOWED_CALL_NUMBERS`, and fewer than `MAX_CALLS_PER_HOUR` calls were placed in the last hour. Each file is processed once. `incoming/` always holds a `README.txt` that keeps the folder visible between uploads; it never triggers a call.
