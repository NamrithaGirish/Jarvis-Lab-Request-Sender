# Jarvis Labs GPU Monitor & Auto-Resume

Automatically polls Jarvis Labs for GPU availability, resumes your paused instance with the desired GPU count, and sends a Slack notification once it's running.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get your Jarvis Labs API token

Go to [Jarvis Labs API Keys](https://jarvislabs.ai/settings/api-keys) and generate a token.

### 3. Create a Slack Incoming Webhook

1. Go to [Slack API — Incoming Webhooks](https://api.slack.com/messaging/webhooks)
2. Create a new app (or use an existing one)
3. Enable **Incoming Webhooks** and create a webhook for your desired channel
4. Copy the webhook URL

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

| Variable | Description |
|---|---|
| `JARVIS_API_TOKEN` | Your Jarvis Labs API token |
| `JARVIS_INSTANCE_NAME` | Name of your instance (as shown in the dashboard) |
| `NUM_GPUS` | Number of GPUs to request (default: 8) |
| `GPU_TYPE` | GPU type — `A100`, `A5000`, `A6000`, `RTX6000Ada`, `RTX5000` |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |
| `RETRY_COOLDOWN_SECONDS` | Seconds to wait between retries after a failed resume (default: 30) |

## Usage

### Run the monitor (no Slack)

```bash
python jarvis_monitor.py
```

### Run with Slack notifications

```bash
python jarvis_monitor.py --slack
```

Pass `--slack` to enable Slack alerts. Without this flag, the script only logs to the console. When enabled, you get a Slack message on **every attempt** (status update) and a final success alert when the instance is running.

### Override settings via CLI

```bash
python jarvis_monitor.py \
  --slack \
  --instance "my-gpu-instance" \
  --num-gpus 8 \
  --gpu-type A100 \
  --retry-cooldown 15
```

### Run in the background

```bash
nohup python jarvis_monitor.py --slack > monitor.log 2>&1 &
```

## How it works

1. Connects to Jarvis Labs API and finds your paused instance
2. Sends a resume request with your requested GPU configuration (e.g. 8 x A100)
3. Checks the instance status immediately after the resume call:
   - **running** — GPUs were available; sends a Slack alert with SSH/URL details and exits
   - **not running** — GPUs not available; notifies about the failure and immediately sends the next resume request
4. On each failed attempt, a short cooldown (`--retry-cooldown`, default 30s) prevents API flooding
5. Sends a Slack update on every attempt when `--slack` is passed
