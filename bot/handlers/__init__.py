"""Handlers package for StoryFlow bot."""

# Commands
from .commands import (
    start,
    help_command,
    queue_command,
)

# Admin & auth
from .admin import (
    handle_admin_input,
    get_auth_code,
    get_auth_password,
    handle_auth_input,
    AUTH_PENDING,
    AUTH_TYPE,
    AUTH_ADMIN_ID,
)

# Document upload (cookies)
from .document import handle_document

# Button callbacks
from .callbacks import button_callback

# URL processing and backlog mode
from .url import (
    handle_url,
    register_backlog_job,
    record_backlog_job_outcome,
    record_backlog_job_failure,
    _CHAT_BURSTS,
    _LAST_BACKLOG_SUBMIT,
    _BACKLOG_LOCKS,
    _BACKLOG_JOBS,
    _DEFERRED_SUMMARY_TASKS,
    _get_backlog_lock,
    _safe_reply,
    _format_burst_summary,
    _deferred_summary_sender,
    _launch_deferred_summary,
    _register_backlog_link,
    PROCESSING_MSGS,
)

# Utilities / dependencies re-exported for backwards compatibility and test patching
from utils.bot_utils import JOB_MESSAGES
from bot.menus import send_cookies_menu

__all__ = [
    'start',
    'help_command',
    'queue_command',
    'handle_admin_input',
    'get_auth_code',
    'get_auth_password',
    'handle_auth_input',
    'handle_document',
    'button_callback',
    'handle_url',
    'register_backlog_job',
    'record_backlog_job_outcome',
    'record_backlog_job_failure',
    'JOB_MESSAGES',
    'send_cookies_menu',
    '_CHAT_BURSTS',
    '_LAST_BACKLOG_SUBMIT',
    '_BACKLOG_LOCKS',
    '_BACKLOG_JOBS',
    '_DEFERRED_SUMMARY_TASKS',
    '_get_backlog_lock',
    '_safe_reply',
    '_format_burst_summary',
    '_deferred_summary_sender',
    '_launch_deferred_summary',
    '_register_backlog_link',
    'PROCESSING_MSGS',
    'AUTH_PENDING',
    'AUTH_TYPE',
    'AUTH_ADMIN_ID',
]
