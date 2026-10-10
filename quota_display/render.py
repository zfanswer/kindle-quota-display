"""Chinese PW3 grayscale frame, rendered on the host with a Simplified Chinese font."""
import argparse
import io
import os
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from .collector import read_snapshot
from .model import PROVIDERS, timestamp, utcnow

WIDTH, HEIGHT = 1072, 1448


def placeholder_frame():
    """Fixed, account-free startup image. Marker distinguishes legacy quota PNGs."""
    return frame(None, _refreshing=True)


@lru_cache(maxsize=32)
def font(size, bold=False):
    configured = os.environ.get("QUOTA_FONT_BOLD" if bold else "QUOTA_FONT")
    if configured:
        return ImageFont.truetype(configured, size, index=int(os.environ.get("QUOTA_FONT_INDEX", "0")))
    candidates = [f"/usr/share/fonts/opentype/noto/NotoSansCJK-{'Bold' if bold else 'Regular'}.ttc",
                  f"/System/Library/Fonts/STHeiti {'Medium' if bold else 'Light'}.ttc",
                  "/System/Library/Fonts/Hiragino Sans GB.ttc"]
    for path in candidates:
        if Path(path).is_file():
            # TTC collections include several regions; choose the SC face by family name.
            for index in range(16):
                try:
                    candidate = ImageFont.truetype(path, size, index=index)
                except OSError:
                    break
                family, style = candidate.getname()
                if family.endswith(" SC") or (family == "Hiragino Sans GB" and style == ("W6" if bold else "W3")):
                    return candidate
    raise RuntimeError("Chinese font missing: install fonts-noto-cjk or set QUOTA_FONT and QUOTA_FONT_BOLD")


def label(w):
    minutes = w["window_minutes"]
    if minutes == 300:
        return "5小时额度"
    if minutes == 10080:
        return "每周额度"
    if minutes:
        return f"{minutes}分钟额度"
    return {"primary": "当前会话", "secondary": "第二窗口", "tertiary": "第三窗口"}[w["id"]]


def frame(data, now=None, tz="Asia/Shanghai", stale_seconds=600, *, _refreshing=False):
    if _refreshing and data is not None:
        raise ValueError("Startup placeholder cannot contain quota data")
    now = now or utcnow()
    zone = ZoneInfo(tz)
    img = Image.new("L", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(img)

    def text(x, y, value, size=30, bold=False, right=False, fill=0):
        f = font(size, bold)
        if right:
            x -= draw.textlength(value, font=f)
        draw.text((x, y), value, font=f, fill=fill)

    text(48, 48, "Agent 额度", 54, True)
    text(48, 124, "剩余额度概览", 26, fill=85)
    # Self-contained provider cards: timestamps belong to the card header.
    margin, gap, cards_top = 48, 32, 192
    card_height = (HEIGHT - cards_top - margin - gap * (len(PROVIDERS) - 1)) // len(PROVIDERS)
    left, right = margin + 32, WIDTH - margin - 32
    for index, (pid, name) in enumerate(PROVIDERS.items()):
        y = cards_top + index * (card_height + gap)
        draw.rounded_rectangle((margin, y, WIDTH - margin, y + card_height), radius=18, outline=0, width=2)
        p = data["providers"][pid] if data else None
        title = {"codex": "Codex", "claude": "Claude Code"}.get(pid, name)
        text(left, y + 32, title, 44, True)
        if _refreshing:
            state = "刷新中"
        elif not p or not p["sampled_at"]:
            state = "暂无数据"
        else:
            sample_age = (now - timestamp(p["sampled_at"])).total_seconds()
            if sample_age < -60:
                state = "时钟异常"
            elif p["status"] == "error":
                state = "采集失败 · 数据过期" if sample_age >= stale_seconds else "采集失败 · 上次数据"
            elif sample_age >= stale_seconds:
                state = "数据过期"
            else:
                state = "正常"
        if _refreshing:
            updated = "等待更新"
        elif p and p["sampled_at"]:
            sample = timestamp(p["sampled_at"]).astimezone(zone)
            updated = "数据更新 " + sample.strftime("%Y-%m-%d %H:%M")
        else:
            updated = "尚无成功采集"
        # The original sample time is the primary freshness signal on a frozen
        # e-ink frame. Keep it black and prominent; status remains below it.
        text(right, y + 44, updated, 26, True, True)
        text(left, y + 100, state, 25, fill=85)
        draw.line((left, y + 140, right, y + 140), fill=170, width=1)
        windows = p["windows"] if p else []
        if not windows:
            text(left, y + 238, "正在刷新quota信息" if _refreshing else "暂无额度数据", 36)
            text(left, y + 300, "请稍候" if _refreshing else "等待首次成功采集", 26, fill=85)
        row_pitch = (card_height - 168 - 32) // max(1, len(windows))
        if windows and row_pitch < 110:
            raise ValueError("Provider/window count exceeds the PW3 single-frame layout")
        compact = len(windows) >= 3
        for wi, w in enumerate(windows):
            top = y + 168 + wi * row_pitch
            text(left, top, label(w), 28 if compact else 32, True)
            percent = w["remaining_percent"]
            # Round down: 0.4% must not promise 1% or suggest an exhausted 0%.
            display = "剩余不足1%" if 0 < percent < 1 else f"剩余 {int(percent)}%"
            text(right, top - 5, display, 38 if compact else 46, True, True)
            bar_top = top + (48 if compact else 56)
            bar_height = 20 if compact else 24
            draw.rectangle((left, bar_top, right, bar_top + bar_height), outline=0, width=2)
            length = int((right - left - 4) * min(100, percent) / 100)
            if length:
                draw.rectangle((left + 2, bar_top + 2, left + 2 + length, bar_top + bar_height - 2), fill=0)
            if w["reset_at"] is None:
                reset = "重置时间未知"
            else:
                reset_date = timestamp(w["reset_at"]).astimezone(zone)
                date_format = "%m月%d日 %H:%M" if reset_date.year == now.astimezone(zone).year else "%Y年%m月%d日 %H:%M"
                reset = "重置于 " + reset_date.strftime(date_format)
                if reset_date <= now:
                    reset += " · 等待新数据"
            text(left, bar_top + bar_height + 16, reset, 23 if compact else 26, fill=85)
    # 16 shades, no alpha; PNG decoder on Kindle does not need transparency.
    img = img.point(lambda p: round(p / 17) * 17)
    output = io.BytesIO()
    info = None
    if _refreshing:
        info = PngImagePlugin.PngInfo()
        info.add_text("kqd-placeholder", "refresh-v1")
    img.save(output, "PNG", optimize=True, pnginfo=info)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--placeholder", action="store_true", help="fixed startup message, no quota input")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now", help="fixed ISO timestamp for reproducible offline previews")
    args = parser.parse_args()
    if args.placeholder and args.now:
        parser.error("--placeholder does not accept timestamps")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(placeholder_frame() if args.placeholder else
                           frame(read_snapshot(args.input), timestamp(args.now) if args.now else utcnow()))


if __name__ == "__main__":
    main()
