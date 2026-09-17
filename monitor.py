"""网站存活监控:定期检测 .env 中配置的网址,下线/恢复时发邮件通知站长。"""

import os
import smtplib
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header

import requests
from dotenv import load_dotenv

load_dotenv()


def log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    site_urls: list
    check_interval: int
    request_timeout: int
    failure_threshold: int
    notify_on_recovery: bool
    up_report_hour: int
    down_report_hour: int
    smtp_host: str
    smtp_port: int
    smtp_use_ssl: bool
    smtp_use_tls: bool
    smtp_user: str
    smtp_password: str
    mail_from: str
    mail_to: list


def load_config() -> Config:
    raw_urls = os.getenv("SITE_URLS", "")
    site_urls = [u.strip() for u in raw_urls.split(",") if u.strip()]
    raw_to = os.getenv("MAIL_TO", "")
    mail_to = [a.strip() for a in raw_to.split(",") if a.strip()]

    missing = []
    if not site_urls:
        missing.append("SITE_URLS")
    if not os.getenv("SMTP_HOST"):
        missing.append("SMTP_HOST")
    if not os.getenv("SMTP_USER"):
        missing.append("SMTP_USER")
    if not os.getenv("SMTP_PASSWORD"):
        missing.append("SMTP_PASSWORD")
    if not mail_to:
        missing.append("MAIL_TO")
    if missing:
        log(f"缺少必要的 .env 配置项: {', '.join(missing)}")
        sys.exit(1)

    return Config(
        site_urls=site_urls,
        check_interval=int(os.getenv("CHECK_INTERVAL_SECONDS", "60")),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", "10")),
        failure_threshold=int(os.getenv("FAILURE_THRESHOLD", "2")),
        notify_on_recovery=env_bool("NOTIFY_ON_RECOVERY", True),
        up_report_hour=int(os.getenv("UP_REPORT_HOUR", "9")),
        down_report_hour=int(os.getenv("DOWN_REPORT_HOUR", "10")),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_use_ssl=env_bool("SMTP_USE_SSL", True),
        smtp_use_tls=env_bool("SMTP_USE_TLS", False),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        mail_from=os.getenv("MAIL_FROM") or os.getenv("SMTP_USER", ""),
        mail_to=mail_to,
    )


@dataclass
class SiteState:
    consecutive_failures: int = 0
    is_down: bool = False
    last_error: str = ""


def check_site(url: str, timeout: int) -> tuple:
    """返回 (是否正常, 错误信息)。"""
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code >= 500:
            return False, f"HTTP {resp.status_code}"
        return True, ""
    except requests.exceptions.RequestException as exc:
        return False, str(exc)


def send_mail(cfg: Config, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = cfg.mail_from
    msg["To"] = ", ".join(cfg.mail_to)

    try:
        if cfg.smtp_use_ssl:
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15)
        with server:
            if cfg.smtp_use_tls and not cfg.smtp_use_ssl:
                server.starttls()
            server.login(cfg.smtp_user, cfg.smtp_password)
            server.sendmail(cfg.mail_from, cfg.mail_to, msg.as_string())
        log(f"已发送邮件通知: {subject}")
    except Exception as exc:
        log(f"发送邮件失败: {exc}")


def send_daily_report(cfg: Config, states: dict, urls_up: bool) -> None:
    if urls_up:
        urls = [url for url in cfg.site_urls if not states[url].is_down]
        if not urls:
            return
        subject = "[网站监控] 每日报告: 正常运行的网站"
        lines = [f"截至 {datetime.now():%Y-%m-%d %H:%M:%S},以下网站运行正常:", ""]
        lines += [f"  - {url}" for url in urls]
    else:
        urls = [url for url in cfg.site_urls if states[url].is_down]
        if not urls:
            return
        subject = "[网站监控] 每日报告: 仍处于下线状态的网站"
        lines = [f"截至 {datetime.now():%Y-%m-%d %H:%M:%S},以下网站仍处于下线状态:", ""]
        for url in urls:
            lines.append(f"  - {url}(最近错误: {states[url].last_error})")
    send_mail(cfg, subject, "\n".join(lines))


def run() -> None:
    cfg = load_config()
    states = {url: SiteState() for url in cfg.site_urls}
    last_up_report_date = None
    last_down_report_date = None

    log(f"开始监控 {len(cfg.site_urls)} 个网站,间隔 {cfg.check_interval} 秒:")
    for url in cfg.site_urls:
        log(f"  - {url}")

    while True:
        for url in cfg.site_urls:
            state = states[url]
            ok, err = check_site(url, cfg.request_timeout)

            if ok:
                if state.is_down:
                    log(f"[恢复] {url} 已恢复上线")
                    if cfg.notify_on_recovery:
                        send_mail(
                            cfg,
                            subject=f"[网站监控] 恢复上线: {url}",
                            body=(
                                f"网站 {url} 已于 {datetime.now():%Y-%m-%d %H:%M:%S} 恢复正常访问。"
                            ),
                        )
                else:
                    log(f"[正常] {url}")
                state.consecutive_failures = 0
                state.is_down = False
            else:
                state.consecutive_failures += 1
                state.last_error = err
                log(
                    f"[异常] {url} 第 {state.consecutive_failures} 次检测失败: {err}"
                )
                if (
                    state.consecutive_failures >= cfg.failure_threshold
                    and not state.is_down
                ):
                    state.is_down = True
                    log(f"[下线] {url} 判定为已下线,发送通知邮件")
                    send_mail(
                        cfg,
                        subject=f"[网站监控] 网站已下线: {url}",
                        body=(
                            f"网站 {url} 于 {datetime.now():%Y-%m-%d %H:%M:%S} "
                            f"检测失败(连续 {state.consecutive_failures} 次)。\n"
                            f"最近一次错误信息: {err}"
                        ),
                    )

        now = datetime.now()
        today = now.date()
        if now.hour >= cfg.up_report_hour and last_up_report_date != today:
            log("[每日报告] 发送正常运行网站报告")
            send_daily_report(cfg, states, urls_up=True)
            last_up_report_date = today
        if now.hour >= cfg.down_report_hour and last_down_report_date != today:
            log("[每日报告] 发送下线网站报告")
            send_daily_report(cfg, states, urls_up=False)
            last_down_report_date = today

        time.sleep(cfg.check_interval)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log("监控已手动停止")
