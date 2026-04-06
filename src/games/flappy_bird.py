from __future__ import annotations

import json
import os
import random
import select
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from ..app_paths import ensure_app_home

_SAVE_DIR = "games"
_SAVE_FILE = "flappy_bird.json"


@dataclass(frozen=True)
class FlappyConfig:
    width: int = 44
    height: int = 14
    pipe_gap: int = 4
    pipe_width: int = 3
    pipe_spacing: int = 16
    gravity: float = 0.28
    flap_velocity: float = -0.95
    max_fall_speed: float = 1.25
    frame_time: float = 0.08


@dataclass
class BirdState:
    x: int
    y: float
    velocity: float = 0.0


@dataclass
class PipeState:
    x: float
    gap_y: int
    scored: bool = False


@dataclass
class FlappyResult:
    score: int
    high_score: int
    quit_requested: bool
    crashed: bool


@dataclass
class FlappyGame:
    config: FlappyConfig = field(default_factory=FlappyConfig)
    rng: random.Random = field(default_factory=random.Random)
    bird: BirdState = field(init=False)
    pipes: list[PipeState] = field(init=False, default_factory=list)
    score: int = field(init=False, default=0)
    crashed: bool = field(init=False, default=False)
    quit_requested: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.bird = BirdState(x=8, y=self.config.height / 2)
        self._seed_pipes()

    def _seed_pipes(self) -> None:
        start = self.config.width + 6
        count = 3
        self.pipes = [
            PipeState(
                x=start + index * self.config.pipe_spacing,
                gap_y=self._random_gap_y(),
            )
            for index in range(count)
        ]

    def _random_gap_y(self) -> int:
        top_margin = 2
        bottom_margin = 2
        min_center = top_margin + self.config.pipe_gap // 2
        max_center = self.config.height - bottom_margin - 1
        return self.rng.randint(min_center, max_center)

    def flap(self) -> None:
        self.bird.velocity = self.config.flap_velocity

    def step(self, flap: bool = False) -> None:
        if self.crashed or self.quit_requested:
            return

        if flap:
            self.flap()

        self.bird.velocity = min(
            self.config.max_fall_speed,
            self.bird.velocity + self.config.gravity,
        )
        self.bird.y += self.bird.velocity

        for pipe in self.pipes:
            pipe.x -= 1

        self._recycle_pipes()
        self._update_score()
        self._detect_collision()

    def _recycle_pipes(self) -> None:
        if self.pipes and self.pipes[0].x + self.config.pipe_width < 0:
            self.pipes.pop(0)
            next_x = self.pipes[-1].x + self.config.pipe_spacing
            self.pipes.append(PipeState(x=next_x, gap_y=self._random_gap_y()))

    def _update_score(self) -> None:
        for pipe in self.pipes:
            if pipe.scored:
                continue
            if pipe.x + self.config.pipe_width < self.bird.x:
                pipe.scored = True
                self.score += 1

    def _detect_collision(self) -> None:
        if self.bird.y < 0 or self.bird.y > self.config.height - 1:
            self.crashed = True
            return

        bird_row = int(round(self.bird.y))
        for pipe in self.pipes:
            pipe_left = int(pipe.x)
            pipe_right = pipe_left + self.config.pipe_width - 1
            if not (pipe_left <= self.bird.x <= pipe_right):
                continue
            gap_top = pipe.gap_y - self.config.pipe_gap // 2
            gap_bottom = gap_top + self.config.pipe_gap - 1
            if not (gap_top <= bird_row <= gap_bottom):
                self.crashed = True
                return

    def frame_text(self, high_score: int) -> str:
        board = [[" " for _ in range(self.config.width)] for _ in range(self.config.height)]

        for pipe in self.pipes:
            pipe_left = max(0, int(pipe.x))
            pipe_right = min(self.config.width - 1, int(pipe.x) + self.config.pipe_width - 1)
            gap_top = pipe.gap_y - self.config.pipe_gap // 2
            gap_bottom = gap_top + self.config.pipe_gap - 1

            for x in range(pipe_left, pipe_right + 1):
                for y in range(self.config.height):
                    if gap_top <= y <= gap_bottom:
                        continue
                    board[y][x] = "█"

        bird_row = max(0, min(self.config.height - 1, int(round(self.bird.y))))
        board[bird_row][self.bird.x] = "@"

        top_border = "┌" + ("─" * self.config.width) + "┐"
        bottom_border = "└" + ("─" * self.config.width) + "┘"
        rows = ["│" + "".join(row) + "│" for row in board]
        hud = f"Score {self.score}  Best {high_score}  Controls: space/up/w jump, q quit"
        return "\n".join([hud, top_border, *rows, bottom_border])


class _TerminalInput:
    def __enter__(self) -> "_TerminalInput":
        self._platform = os.name
        self._fd: int | None = None
        self._old_settings = None
        self._msvcrt = None
        if self._platform == "nt":
            import msvcrt  # type: ignore

            self._msvcrt = msvcrt
            return self

        if not sys.stdin.isatty():
            return self

        import termios
        import tty

        self._fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._platform != "nt" and self._fd is not None and self._old_settings is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)

    def read_key(self) -> str | None:
        if self._platform == "nt":
            if self._msvcrt is None or not self._msvcrt.kbhit():
                return None
            raw = self._msvcrt.getwch()
            if raw in ("\x00", "\xe0") and self._msvcrt.kbhit():
                arrow = self._msvcrt.getwch()
                return {"H": "UP"}.get(arrow, arrow)
            return raw

        if not sys.stdin.isatty():
            return None

        readable, _, _ = select.select([sys.stdin], [], [], 0)
        if not readable:
            return None
        raw = sys.stdin.read(1)
        if raw == "\x1b":
            readable, _, _ = select.select([sys.stdin], [], [], 0)
            if readable:
                rest = sys.stdin.read(2)
                if rest == "[A":
                    return "UP"
            return raw
        return raw


def _score_path(cwd: str | None = None) -> Path:
    return ensure_app_home(cwd) / _SAVE_DIR / _SAVE_FILE


def load_high_score(cwd: str | None = None) -> int:
    path = _score_path(cwd)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 0
    value = payload.get("top_score", 0)
    return value if isinstance(value, int) and value >= 0 else 0


def save_high_score(score: int, cwd: str | None = None) -> int:
    high_score = max(score, load_high_score(cwd))
    path = _score_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"top_score": high_score}, indent=2) + "\n", encoding="utf-8")
    return high_score


def _render_screen(game: FlappyGame, high_score: int, footer: str) -> Group:
    body = Text(game.frame_text(high_score))
    return Group(Panel(body, title="Flappy Bird", border_style="cyan"), Text(footer, style="dim"))


def _is_jump_key(key: str | None) -> bool:
    return key in (" ", "w", "W", "UP")


def _is_exit_key(key: str | None) -> bool:
    return key in ("q", "Q", "e", "E", "\x1b")


def _wait_for_start(keys: _TerminalInput, live: Live, game: FlappyGame, high_score: int) -> bool:
    footer = "Press space to start. Press q to exit."
    live.update(_render_screen(game, high_score, footer))
    while True:
        key = keys.read_key()
        if _is_jump_key(key):
            return True
        if _is_exit_key(key):
            return False
        time.sleep(0.02)


def _wait_for_restart(keys: _TerminalInput, live: Live, game: FlappyGame, high_score: int) -> bool:
    footer = "Crash! Press r, Enter, or space to restart. Press q to exit."
    live.update(_render_screen(game, high_score, footer))
    while True:
        key = keys.read_key()
        if key in ("r", "R", "\r", "\n") or _is_jump_key(key):
            return True
        if _is_exit_key(key):
            return False
        time.sleep(0.02)


def run_flappy_bird(
    cwd: str | None = None,
    *,
    console: Console | None = None,
    max_frames: int | None = None,
    out: TextIO | None = None,
) -> FlappyResult:
    console = console or Console()
    config = FlappyConfig()
    high_score = load_high_score(cwd)
    last_score = 0
    crashed = False
    quit_requested = False

    with _TerminalInput() as keys:
        with Live(
            Text(""),
            console=console,
            refresh_per_second=max(1, int(1 / config.frame_time)),
            transient=False,
        ) as live:
            while True:
                game = FlappyGame(config=config)
                frame_count = 0

                if max_frames is None and not _wait_for_start(keys, live, game, high_score):
                    quit_requested = True
                    last_score = 0
                    crashed = False
                    break

                while not game.crashed and not game.quit_requested:
                    start = time.monotonic()
                    flap = False

                    key = keys.read_key()
                    if _is_jump_key(key):
                        flap = True
                    elif _is_exit_key(key):
                        game.quit_requested = True
                        break

                    game.step(flap=flap)
                    if game.score > high_score:
                        high_score = game.score
                    live.update(
                        _render_screen(
                            game,
                            high_score,
                            "Thread the gap and keep the bird airborne. Press q to exit.",
                        )
                    )
                    frame_count += 1
                    if max_frames is not None and frame_count >= max_frames:
                        break

                    elapsed = time.monotonic() - start
                    if elapsed < game.config.frame_time:
                        time.sleep(game.config.frame_time - elapsed)

                last_score = game.score
                crashed = game.crashed
                quit_requested = game.quit_requested

                if game.score >= high_score:
                    high_score = save_high_score(game.score, cwd)
                elif game.score > 0:
                    save_high_score(high_score, cwd)

                if max_frames is not None:
                    break
                if game.quit_requested:
                    break
                if not game.crashed:
                    break
                if not _wait_for_restart(keys, live, game, high_score):
                    quit_requested = True
                    break

    stream = out if out is not None else console.file
    if max_frames is None:
        stream.write("\n")
        if crashed:
            stream.write(f"Crashed with score {last_score}. Best: {high_score}.\n")
        elif quit_requested:
            stream.write(f"Exited with score {last_score}. Best: {high_score}.\n")
        else:
            stream.write(f"Finished with score {last_score}. Best: {high_score}.\n")
        if hasattr(stream, "flush"):
            stream.flush()

    return FlappyResult(
        score=last_score,
        high_score=high_score,
        quit_requested=quit_requested,
        crashed=crashed,
    )


__all__ = [
    "FlappyConfig",
    "FlappyGame",
    "FlappyResult",
    "load_high_score",
    "run_flappy_bird",
    "save_high_score",
]
