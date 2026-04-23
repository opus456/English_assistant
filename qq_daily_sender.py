from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


LOGGER = logging.getLogger("cet6_qq_sender")


@dataclass(slots=True)
class PushTarget:
    target_type: str
    target_id: str


@dataclass(slots=True)
class DailyAssets:
    date_label: str
    daily_dir: Path
    test_pdf: Path
    answer_pdf: Path
    ai_output_path: Path | None


@dataclass(slots=True)
class AppConfig:
    mode: str
    timezone: str
    send_time: str
    poll_seconds: int
    dry_run: bool
    force: bool
    target: PushTarget
    article_root: Path
    napcat_shared_root: Path
    local_article_root: Path
    napcat_api_base: str
    napcat_access_token: str | None
    state_file: Path
    message_prefix: str
    date_label: str | None
    env_file: Path


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send the latest CET-6 PDF package through NapCat OneBot HTTP API."
    )
    parser.add_argument(
        "--mode",
        choices=["once", "scheduler"],
        default=os.environ.get("CET6_BOT_RUN_MODE", "once"),
        help="Run once immediately or keep scheduling daily sends.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("CET6_BOT_ENV_FILE", ".env"),
        help="Environment file path.",
    )
    parser.add_argument(
        "--date-label",
        default=os.environ.get("CET6_BOT_DATE_LABEL"),
        help="Specific date folder to send, for example 04-23.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=env_bool("CET6_BOT_DRY_RUN", False),
        help="Resolve files and log the outgoing actions without calling NapCat.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=env_bool("CET6_BOT_FORCE", False),
        help="Ignore same-day sent state and send again.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("CET6_BOT_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level.",
    )
    return parser


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def build_config(args: argparse.Namespace) -> AppConfig:
    timezone = os.environ.get("APP_TIMEZONE", "Asia/Shanghai")
    target_type = os.environ.get("QQ_TARGET_TYPE", "private").strip().lower()
    if target_type not in {"private", "group"}:
        raise RuntimeError("QQ_TARGET_TYPE must be either 'private' or 'group'.")

    target_id = os.environ.get("QQ_TARGET_ID", "").strip()
    if not target_id:
        raise RuntimeError("Missing QQ_TARGET_ID in environment.")

    napcat_api_base = os.environ.get("NAPCAT_API_BASE", "http://napcat:3000").rstrip("/")
    article_root = Path(os.environ.get("ARTICLES_ROOT", "articles"))
    local_article_root = Path(os.environ.get("LOCAL_ARTICLE_ROOT", str(article_root)))
    napcat_shared_root = Path(os.environ.get("NAPCAT_SHARED_ROOT", "/data/shared/articles"))
    state_file = Path(os.environ.get("CET6_BOT_STATE_FILE", "runtime/qq-push-state.json"))
    poll_seconds = env_int("CET6_BOT_POLL_SECONDS", 20)
    send_time = os.environ.get("CET6_BOT_SEND_TIME", "07:30")
    message_prefix = os.environ.get("QQ_MESSAGE_PREFIX", "CET6 Daily Flow")

    return AppConfig(
        mode=args.mode,
        timezone=timezone,
        send_time=send_time,
        poll_seconds=poll_seconds,
        dry_run=args.dry_run,
        force=args.force,
        target=PushTarget(target_type=target_type, target_id=target_id),
        article_root=article_root,
        napcat_shared_root=napcat_shared_root,
        local_article_root=local_article_root,
        napcat_api_base=napcat_api_base,
        napcat_access_token=os.environ.get("NAPCAT_ACCESS_TOKEN") or None,
        state_file=state_file,
        message_prefix=message_prefix,
        date_label=args.date_label,
        env_file=Path(args.env_file),
    )


def current_local_time(config: AppConfig) -> datetime:
    return datetime.now(ZoneInfo(config.timezone))


def today_label(config: AppConfig) -> str:
    return current_local_time(config).strftime("%m-%d")


def validate_send_time(send_time: str) -> None:
    parts = send_time.split(":")
    if len(parts) != 2:
        raise RuntimeError("CET6_BOT_SEND_TIME must be in HH:MM format.")

    hour, minute = parts
    if not hour.isdigit() or not minute.isdigit():
        raise RuntimeError("CET6_BOT_SEND_TIME must be in HH:MM format.")

    hour_value = int(hour)
    minute_value = int(minute)
    if hour_value < 0 or hour_value > 23 or minute_value < 0 or minute_value > 59:
        raise RuntimeError("CET6_BOT_SEND_TIME must be a valid 24-hour time.")


def load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {}

    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("State file is invalid JSON, ignoring existing state: %s", state_file)
        return {}


def save_state(state_file: Path, state: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def state_key(config: AppConfig) -> str:
    return f"{config.target.target_type}:{config.target.target_id}"


def resolve_daily_assets(config: AppConfig, date_label: str | None = None) -> DailyAssets:
    resolved_date = date_label or config.date_label or today_label(config)
    daily_dir = config.article_root / resolved_date
    if not daily_dir.exists():
        raise FileNotFoundError(f"Daily article folder not found: {daily_dir}")

    test_candidates = sorted(daily_dir.glob("*-test.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not test_candidates:
        raise FileNotFoundError(f"No test PDF found in {daily_dir}")

    test_pdf = test_candidates[0]
    answer_name = test_pdf.name[:-9] + "-answer.pdf"
    answer_pdf = daily_dir / answer_name
    if not answer_pdf.exists():
        raise FileNotFoundError(f"Missing answer PDF for {test_pdf.name}")

    ai_output_candidates = sorted(daily_dir.glob("*_ai_output.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    ai_output_path = ai_output_candidates[0] if ai_output_candidates else None

    return DailyAssets(
        date_label=resolved_date,
        daily_dir=daily_dir,
        test_pdf=test_pdf,
        answer_pdf=answer_pdf,
        ai_output_path=ai_output_path,
    )


def read_ai_summary(ai_output_path: Path | None) -> dict[str, Any]:
    if ai_output_path is None or not ai_output_path.exists():
        return {}

    try:
        return json.loads(ai_output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("Failed to parse AI output JSON: %s", ai_output_path)
        return {}


def build_push_message(config: AppConfig, assets: DailyAssets) -> str:
    summary = read_ai_summary(assets.ai_output_path)
    metadata = summary.get("article_metadata", {}) if isinstance(summary, dict) else {}
    exercise = summary.get("exercise", {}) if isinstance(summary, dict) else {}
    learning_package = summary.get("learning_package", {}) if isinstance(summary, dict) else {}

    vocab_items = learning_package.get("vocabulary", []) if isinstance(learning_package, dict) else []
    vocab_preview = "、".join(item.get("word", "") for item in vocab_items[:3] if isinstance(item, dict) and item.get("word"))
    if not vocab_preview:
        vocab_preview = "今日词汇已附在解析卷中"

    question_count = len(exercise.get("questions", [])) if isinstance(exercise.get("questions"), list) else 0
    title = metadata.get("title") or assets.test_pdf.stem.removesuffix("-test")
    source = metadata.get("source") or "Unknown Source"
    exercise_type = exercise.get("type") or "unknown"

    return (
        f"{config.message_prefix}\n"
        f"日期：{assets.date_label}\n"
        f"文章：{title}\n"
        f"来源：{source}\n"
        f"题型：{exercise_type}\n"
        f"题目数：{question_count}\n"
        f"词汇预览：{vocab_preview}\n\n"
        "已附上今日试卷与解析 PDF。"
    )


def map_to_napcat_path(config: AppConfig, local_path: Path) -> str:
    resolved_local_root = config.local_article_root.resolve()
    resolved_path = local_path.resolve()
    try:
        relative_path = resolved_path.relative_to(resolved_local_root)
    except ValueError as exc:
        raise RuntimeError(
            f"File {resolved_path} is outside LOCAL_ARTICLE_ROOT {resolved_local_root}"
        ) from exc
    return str((config.napcat_shared_root / relative_path).as_posix())


class NapCatClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def call_action(self, action: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.config.napcat_api_base}/{action.lstrip('/')}"
        body = json.dumps(params or {}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "CET6-Daily-Flow/1.0",
        }
        if self.config.napcat_access_token:
            headers["Authorization"] = f"Bearer {self.config.napcat_access_token}"

        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"NapCat HTTP error {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"NapCat connection failed: {exc}") from exc

        status = payload.get("status")
        if status not in {"ok", "async"}:
            raise RuntimeError(f"NapCat action {action} failed: {payload}")
        return payload.get("data")

    def get_login_info(self) -> dict[str, Any]:
        data = self.call_action("get_login_info")
        return data if isinstance(data, dict) else {}

    def send_text(self, target: PushTarget, message: str) -> Any:
        if target.target_type == "private":
            return self.call_action(
                "send_private_msg",
                {"user_id": target.target_id, "message": message, "auto_escape": True},
            )

        return self.call_action(
            "send_group_msg",
            {"group_id": target.target_id, "message": message, "auto_escape": True},
        )

    def upload_file(self, target: PushTarget, file_path: str, display_name: str) -> Any:
        if target.target_type == "private":
            return self.call_action(
                "upload_private_file",
                {"user_id": target.target_id, "file": file_path, "name": display_name},
            )

        return self.call_action(
            "upload_group_file",
            {"group_id": target.target_id, "file": file_path, "name": display_name},
        )


def execute_send(config: AppConfig) -> DailyAssets:
    assets = resolve_daily_assets(config)
    message = build_push_message(config, assets)
    test_path_in_napcat = map_to_napcat_path(config, assets.test_pdf)
    answer_path_in_napcat = map_to_napcat_path(config, assets.answer_pdf)

    LOGGER.info("Resolved daily folder: %s", assets.daily_dir)
    LOGGER.info("Resolved test PDF: %s", assets.test_pdf)
    LOGGER.info("Resolved answer PDF: %s", assets.answer_pdf)

    if config.dry_run:
        LOGGER.info("Dry-run enabled, outgoing message:\n%s", message)
        LOGGER.info("Dry-run NapCat file path(test): %s", test_path_in_napcat)
        LOGGER.info("Dry-run NapCat file path(answer): %s", answer_path_in_napcat)
        return assets

    client = NapCatClient(config)
    login_info = client.get_login_info()
    LOGGER.info(
        "Connected to NapCat bot account: %s (%s)",
        login_info.get("nickname", "unknown"),
        login_info.get("user_id", "unknown"),
    )

    client.send_text(config.target, message)
    time.sleep(1)
    client.upload_file(config.target, test_path_in_napcat, assets.test_pdf.name)
    time.sleep(1)
    client.upload_file(config.target, answer_path_in_napcat, assets.answer_pdf.name)
    time.sleep(1)
    client.send_text(
        config.target,
        f"{config.message_prefix} 推送完成，祝你今天刷题顺利。",
    )
    return assets


def should_send_now(config: AppConfig, state: dict[str, Any]) -> bool:
    if config.force:
        return True

    now = current_local_time(config)
    if now.strftime("%H:%M") != config.send_time:
        return False

    key = state_key(config)
    target_state = state.get(key, {})
    return target_state.get("date") != today_label(config)


def mark_sent(config: AppConfig, state: dict[str, Any], assets: DailyAssets) -> None:
    key = state_key(config)
    state[key] = {
        "date": assets.date_label,
        "test_pdf": assets.test_pdf.name,
        "answer_pdf": assets.answer_pdf.name,
        "sent_at": current_local_time(config).isoformat(),
    }
    save_state(config.state_file, state)


def run_once(config: AppConfig) -> int:
    try:
        assets = execute_send(config)
    except Exception as exc:
        LOGGER.error("Send failed: %s", exc)
        return 1

    if not config.dry_run:
        state = load_state(config.state_file)
        mark_sent(config, state, assets)
    return 0


def run_scheduler(config: AppConfig) -> int:
    validate_send_time(config.send_time)
    LOGGER.info(
        "Scheduler started. timezone=%s send_time=%s poll_seconds=%s target=%s:%s",
        config.timezone,
        config.send_time,
        config.poll_seconds,
        config.target.target_type,
        config.target.target_id,
    )

    while True:
        state = load_state(config.state_file)
        try:
            if should_send_now(config, state):
                assets = execute_send(config)
                if not config.dry_run:
                    mark_sent(config, state, assets)
            time.sleep(config.poll_seconds)
        except KeyboardInterrupt:
            LOGGER.info("Scheduler interrupted, exiting.")
            return 0
        except Exception as exc:
            LOGGER.exception("Scheduler loop failed: %s", exc)
            time.sleep(config.poll_seconds)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    load_env_file(Path(args.env_file))
    configure_logging(args.log_level)
    config = build_config(args)
    validate_send_time(config.send_time)

    if config.mode == "once":
        return run_once(config)
    return run_scheduler(config)


if __name__ == "__main__":
    raise SystemExit(main())