"""Скриншоты для README и видеозапись демонстрации (запасной вариант на случай сбоя связи на защите).

Требуется запущенная система (docker compose up -d) и Playwright с Chrome:
  .venv/bin/python docs/scripts/capture_demo.py [--url http://localhost:8000] [--video]
Пароль администратора берётся из .env (EIS_ADMIN_PASSWORD), в выводе не печатается.
Результат: docs/figures/ui_*.png, docs/competition/demo.mp4 (при --video и наличии ffmpeg).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def env_password() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("EIS_ADMIN_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("В .env нет EIS_ADMIN_PASSWORD")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--video", action="store_true")
    a = ap.parse_args()
    figs = ROOT / "docs" / "figures"
    vdir = ROOT / "docs" / "competition" / ".video"
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900},
                            record_video_dir=str(vdir) if a.video else None, record_video_size={"width": 1440, "height": 900})
        pg = ctx.new_page()
        pause = (lambda ms: pg.wait_for_timeout(ms)) if a.video else (lambda ms: pg.wait_for_timeout(min(ms, 1500)))
        pg.goto(a.url + "/login")
        pg.fill("input[autocomplete=username]", "admin")
        pg.fill("input[autocomplete=current-password]", env_password())
        pg.click("button[type=submit]")
        pause(2500)
        pg.screenshot(path=str(figs / "ui_dashboard.png"))
        pg.goto(a.url + "/documents"); pause(2500)
        pg.screenshot(path=str(figs / "ui_documents.png"))
        pg.click("td >> text=НА-200.00.000 РЭ"); pause(3000)
        pg.goto(a.url + "/graph"); pause(3500)
        pg.goto(a.url + "/impact"); pause(1500)
        pg.click("text=Текст извещения")
        pg.click("text=Номинальная мощность электродвигателя увеличивается"); pause(1200)
        pg.click("text=Запустить анализ"); pause(3500)
        pg.screenshot(path=str(figs / "ui_impact.png"))
        pg.mouse.wheel(0, 600); pause(2500)
        pg.click("text=На графе"); pause(4000)
        pg.screenshot(path=str(figs / "ui_impact_graph.png"))
        pg.goto(a.url + "/contradictions"); pause(3500)
        pg.screenshot(path=str(figs / "ui_contradictions.png"))
        pg.mouse.wheel(0, 500); pause(2500)
        pg.goto(a.url + "/assistant"); pause(1500)
        pg.fill("input[placeholder^='Вопрос']", "Какое значение параметра «мощность» для «электродвигатель» указано в документе НА-200.00.000 ТЗ?")
        pg.keyboard.press("Enter"); pause(12000)
        pg.screenshot(path=str(figs / "ui_assistant.png"))
        video = pg.video.path() if a.video else None
        ctx.close()
        b.close()
    if video:
        out = ROOT / "docs" / "competition" / "demo.mp4"
        if shutil.which("ffmpeg"):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-crf", "28", "-preset", "slow", str(out)], check=True)
            shutil.rmtree(vdir, ignore_errors=True)
            print("видео:", out.relative_to(ROOT), f"{out.stat().st_size / 2**20:.1f} МБ")
        else:
            print("видео (webm):", video)
    print("скриншоты: docs/figures/ui_*.png")


if __name__ == "__main__":
    main()
