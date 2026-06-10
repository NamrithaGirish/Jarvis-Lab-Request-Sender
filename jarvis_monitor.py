#!/usr/bin/env python3
"""
Jarvis Labs GPU Monitor & Auto-Resume

Sends resume requests to Jarvis Labs until the instance is running,
then sends a Slack alert. The JLClient library handles status polling
internally (up to ~3 min per attempt), so no manual sleep/poll is needed.
"""

import os
import sys
import time
import argparse
import logging
from datetime import datetime

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from jlclient import jarvisclient
from jlclient.jarvisclient import User, Instance

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def send_slack(
    slack_client: WebClient | None,
    channel: str | None,
    message: str,
    is_error: bool = False,
):
    if not slack_client or not channel:
        return

    color = "#ff0000" if is_error else "#36a64f"
    icon = ":x:" if is_error else ":white_check_mark:"
    try:
        slack_client.chat_postMessage(
            channel=channel,
            text=f"{icon} {message}",
            attachments=[
                {
                    "color": color,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"{icon} {message}",
                            },
                        }
                    ],
                }
            ],
        )
    except SlackApiError as exc:
        log.error("Failed to send Slack notification: %s", exc.response["error"])


def find_instance(instance_name: str) -> Instance | None:
    for inst in User.get_instances():
        if inst.name == instance_name:
            return inst
    return None


def run(
    api_token: str,
    instance_name: str,
    num_gpus: int,
    gpu_type: str,
    slack_client: WebClient | None,
    slack_channel: str | None,
    retry_cooldown: int,
):
    jarvisclient.token = api_token

    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    send_slack(
        slack_client,
        slack_channel,
        f"*Jarvis Labs Monitor Started* :eyes:\n"
        f"Instance `{instance_name}` | {num_gpus} x {gpu_type}\n"
        f"Retry cooldown: {retry_cooldown}s\n"
        f"Started at: {start_time}",
    )

    log.info("Looking for instance '%s'…", instance_name)
    instance = find_instance(instance_name)
    if instance is None:
        log.error("Instance '%s' not found. Available instances:", instance_name)
        for inst in User.get_instances():
            log.error("  - %s (status: %s)", inst.name, inst.status)
        sys.exit(1)

    log.info("Found '%s' — status: %s", instance.name, instance.status)

    if instance.status.lower() == "running":
        log.info("Instance is already running!")
        send_slack(
            slack_client,
            slack_channel,
            f"*Jarvis Labs Instance Ready*\n"
            f"Instance `{instance.name}` is already *running*.\n"
            f"GPUs: {instance.num_gpus} x {instance.gpu_type}",
        )
        return

    if instance.status.lower() != "paused":
        log.error("Instance is in '%s' state — expected 'paused'. Exiting.", instance.status)
        sys.exit(1)

    attempt = 0
    while True:
        attempt += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.info("=== Attempt %d · %s ===", attempt, now)
        log.info("Sending resume request: %d x %s …", num_gpus, gpu_type)

        try:
            result = instance.resume(num_gpus=num_gpus, gpu_type=gpu_type)
        except Exception as exc:
            # InstanceCreationException: timed out waiting or status became "Failed"
            error_msg = str(exc)
            log.warning("Resume raised an exception: %s", error_msg)
            time.sleep(retry_cooldown)
            instance = find_instance(instance_name) or instance
            continue

        # resume() returns a dict with 'error_message' when GPUs aren't available
        if isinstance(result, dict) and "error_message" in result:
            error_msg = result["error_message"]
            log.info("GPUs not available: %s", error_msg)
            time.sleep(retry_cooldown)
            instance = find_instance(instance_name) or instance
            continue

        # resume() returned the Instance object — VM is running
        log.info("Instance is RUNNING!")
        send_slack(
            slack_client,
            slack_channel,
            f"*Jarvis Labs Instance Ready* :rocket:\n"
            f"Instance `{instance.name}` is now *running*!\n"
            f"GPUs: {num_gpus} x {gpu_type}\n"
            f"SSH: `{instance.ssh_str}`\n"
            f"URL: {instance.url}\n"
            f"Resumed at: {now} (after {attempt} attempt(s))",
        )
        log.info("SSH: %s", instance.ssh_str)
        log.info("URL: %s", instance.url)
        return


def main():
    parser = argparse.ArgumentParser(
        description="Monitor Jarvis Labs GPU availability and auto-resume an instance.",
    )
    parser.add_argument("--token", default=os.getenv("JARVIS_API_TOKEN"))
    parser.add_argument("--instance", default=os.getenv("JARVIS_INSTANCE_NAME"))
    parser.add_argument("--num-gpus", type=int, default=int(os.getenv("NUM_GPUS", "8")))
    parser.add_argument("--gpu-type", default=os.getenv("GPU_TYPE", "H100"))
    parser.add_argument("--slack", action="store_true", default=False, help="Enable Slack notifications")
    parser.add_argument("--slack-token", default=os.getenv("SLACK_BOT_TOKEN"),
                        help="Slack Bot token (xoxb-…). Falls back to SLACK_BOT_TOKEN env var.")
    parser.add_argument("--slack-channel", default=os.getenv("SLACK_CHANNEL"),
                        help="Slack channel to post to (e.g. #gpu-alerts or C0123456789). Falls back to SLACK_CHANNEL env var.")
    parser.add_argument("--retry-cooldown", type=int, default=int(os.getenv("RETRY_COOLDOWN_SECONDS", "30")),
                        help="Seconds to wait between failed attempts")

    args = parser.parse_args()

    if not args.token:
        log.error("JARVIS_API_TOKEN is required. Set it in .env or pass --token.")
        sys.exit(1)
    if not args.instance:
        log.error("JARVIS_INSTANCE_NAME is required. Set it in .env or pass --instance.")
        sys.exit(1)

    slack_client = None
    slack_channel = None
    if args.slack:
        if not args.slack_token:
            log.error("--slack flag set but no bot token. Set SLACK_BOT_TOKEN in .env or pass --slack-token.")
            sys.exit(1)
        if not args.slack_channel:
            log.error("--slack flag set but no channel. Set SLACK_CHANNEL in .env or pass --slack-channel.")
            sys.exit(1)
        slack_client = WebClient(token=args.slack_token)
        slack_channel = args.slack_channel

    run(
        api_token=args.token,
        instance_name=args.instance,
        num_gpus=args.num_gpus,
        gpu_type=args.gpu_type,
        slack_client=slack_client,
        slack_channel=slack_channel,
        retry_cooldown=args.retry_cooldown,
    )


if __name__ == "__main__":
    main()
