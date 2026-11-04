"""
Ardor Gaming — полноэкранный игровой лаунчер (консольная оболочка поверх Windows).

Стек: Python 3.10+, PyQt6, PyQt6-Multimedia, pygame (только joystick-подсистема).
Управление: геймпад (основное) + клавиатура (fallback).

Запуск:  python main.py
"""

from __future__ import annotations

import json
from collections import OrderedDict
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Пути и логирование (всё строго от BASE_DIR, независимо от cwd)
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent
ASSETS_DIR: Path = BASE_DIR / "assets"
GAMES_JSON: Path = BASE_DIR / "games.json"
SETTINGS_JSON: Path = BASE_DIR / "settings.json"
LOG_FILE: Path = BASE_DIR / "launcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ardor")

# pygame — опциональная зависимость. ВАЖНО: никогда не вызывать pygame.init()
# (он инициализирует SDL2-аудио и конфликтует с QMediaPlayer).
try:
    import pygame  # type: ignore

    PYGAME_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    pygame = None  # type: ignore
    PYGAME_AVAILABLE = False
    log.warning("pygame не установлен — управление только клавиатурой.")

from PyQt6.QtCore import (
    QPropertyAnimation,
    QEasingCurve,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QUrl,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QImage,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QKeyEvent,
    QMouseEvent,
    QPixmap,
)
try:
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect

    MULTIMEDIA_AVAILABLE: bool = True
except ImportError as _mm_err:  # PyQt6-Multimedia не установлен — работаем без звука
    QAudioOutput = None  # type: ignore[assignment,misc]
    QMediaPlayer = None  # type: ignore[assignment,misc]
    QSoundEffect = None  # type: ignore[assignment,misc]
    MULTIMEDIA_AVAILABLE = False
    log.warning("PyQt6-Multimedia недоступен (%s) — запуск без аудио.", _mm_err)

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGraphicsScene,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

ACCENT: str = "#E60000"
PANEL: str = "#1A0A0A"
PANEL2: str = "#2A0F0F"
TEXT: str = "#FFFFFF"
TEXT2: str = "#B0B0B0"


# ──────────────────────────────────────────────────────────────────────────────
# Стили (QSS)
# ──────────────────────────────────────────────────────────────────────────────
def build_qss(scale: float = 1.0) -> str:
    """Основная таблица стилей. scale — коэффициент от базового 1080p."""
    px = lambda v: int(round(v * scale))  # noqa: E731
    return f"""
    QWidget {{
        background-color: #000000;
        color: {TEXT};
        font-family: "Segoe UI", Arial, sans-serif;
    }}
    QLabel#logo {{
        color: {TEXT};
        font-size: {px(28)}px;
        font-weight: 900;
        letter-spacing: 4px;
        background: transparent;
    }}
    QLabel#logo span, QLabel#activeTitle {{
        color: {TEXT};
    }}
    QLabel#activeTitle {{
        font-size: {px(22)}px;
        font-weight: 700;
        color: {TEXT};
        background: transparent;
    }}
    QLabel#gameName {{
        font-size: {px(48)}px;
        font-weight: bold;
        color: {TEXT};
        background: transparent;
    }}
    QLabel#gameDesc {{
        font-size: {px(18)}px;
        color: {TEXT2};
        background: transparent;
    }}
    QLabel#slotLabel {{
        font-size: {px(16)}px;
        color: {TEXT2};
        background: transparent;
    }}
    QLabel#statusText {{
        font-size: {px(14)}px;
        color: {TEXT2};
        background: transparent;
    }}
    QLabel#clock {{
        font-size: {px(22)}px;
        font-weight: 600;
        color: {TEXT};
        background: transparent;
    }}
    QLabel#toast {{
        background-color: rgba(26, 10, 10, 0.92);
        border: 1px solid {ACCENT};
        border-radius: {px(10)}px;
        padding: {px(10)}px {px(20)}px;
        font-size: {px(16)}px;
        color: {TEXT};
    }}
    QPushButton {{
        background-color: transparent;
        border: 2px solid {ACCENT};
        border-radius: {px(12)}px;
        padding: {px(12)}px {px(24)}px;
        color: {TEXT};
        font-size: {px(16)}px;
        font-weight: 600;
    }}
    QPushButton:hover, QPushButton:focus {{
        background-color: {ACCENT};
        color: #000000;
        border-color: #FF3333;
    }}
    QPushButton:pressed {{
        background-color: #FF3333;
        color: #000000;
    }}
    QPushButton:default {{
        border-color: #FF3333;
    }}
    QLineEdit {{
        background-color: {PANEL};
        border: 1px solid {ACCENT};
        border-radius: {px(8)}px;
        padding: {px(8)}px;
        color: {TEXT};
        font-size: {px(15)}px;
        selection-background-color: {ACCENT};
        selection-color: #000000;
    }}
    QLineEdit:focus {{
        border: 1px solid #FF3333;
    }}
    QSlider::groove:horizontal {{
        height: {px(6)}px;
        background: {PANEL2};
        border-radius: {px(3)}px;
    }}
    QSlider::sub-page:horizontal {{
        background: {ACCENT};
        border-radius: {px(3)}px;
    }}
    QSlider::handle:horizontal {{
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.6,
            stop:0 #FF4444, stop:1 {ACCENT});
        width: {px(20)}px;
        height: {px(20)}px;
        margin: {-px(8)}px 0;
        border-radius: {px(10)}px;
    }}
    QSlider::handle:horizontal:focus {{
        background: #FF3333;
    }}
    QDialog#glassDialog {{
        background-color: rgba(0, 0, 0, 0.85);
        border: 1px solid {ACCENT};
        border-radius: {px(16)}px;
    }}
    QLabel#dialogTitle {{
        font-size: {px(26)}px;
        font-weight: 800;
        color: {TEXT};
        background: transparent;
    }}
    QLabel#fieldLabel {{
        font-size: {px(14)}px;
        font-weight: 600;
        color: {TEXT};
        background: transparent;
    }}
    QLabel#hint {{
        font-size: {px(12)}px;
        color: {TEXT2};
        background: transparent;
    }}
    QLabel#tabLabel {{
        font-size: {px(18)}px;
        color: {TEXT2};
        background: transparent;
        padding: {px(8)}px {px(14)}px;
        border-left: 3px solid transparent;
    }}
    QLabel#tabActive {{
        font-size: {px(18)}px;
        font-weight: 700;
        color: {TEXT};
        background-color: {PANEL};
        padding: {px(8)}px {px(14)}px;
        border-left: 3px solid {ACCENT};
    }}
    QFrame#panel {{
        background-color: {PANEL};
        border: 1px solid {PANEL2};
        border-radius: {px(14)}px;
    }}
    """


# ──────────────────────────────────────────────────────────────────────────────
# Модели данных
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Game:
    id: str
    title: str
    description: str
    exe_path: str
    icon: str = ""
    cover: str = ""
    background: str = ""

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Game":
        return Game(
            id=str(d.get("id") or uuid.uuid4()),
            title=str(d.get("title", "Без названия")),
            description=str(d.get("description", "")),
            exe_path=str(d.get("exe_path", "")),
            icon=str(d.get("icon", "")),
            cover=str(d.get("cover", "")),
            background=str(d.get("background", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "exe_path": self.exe_path,
            "icon": self.icon,
            "cover": self.cover,
            "background": self.background,
        }


DEFAULT_SETTINGS: Dict[str, Any] = {
    "music_volume": 70,
    "sfx_volume": 80,
    "music_file": "menu_theme.mp3",
    "sounds": {"hover": "hover.wav", "select": "select.wav", "back": "back.wav"},
    "gamepad": {
        "enabled": True,
        "deadzone": 0.3,
        "repeat_delay_ms": 400,
        "repeat_interval_ms": 150,
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# StorageManager — games.json / settings.json с защитой от битых файлов
# ──────────────────────────────────────────────────────────────────────────────
class StorageManager:
    def __init__(self) -> None:
        self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.games: List[Game] = []
        self.load_settings()
        self.load_games()

    # -- настройки --------------------------------------------------------
    def load_settings(self) -> None:
        try:
            with open(SETTINGS_JSON, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("settings.json root is not an object")
            merged = _deep_merge(dict(DEFAULT_SETTINGS), raw)
            self.settings = merged
        except Exception as exc:
            log.warning("settings.json отсутствует/бит (%s) — создаю дефолтный.", exc)
            self.settings = json.loads(json.dumps(DEFAULT_SETTINGS))
            self.save_settings()

    def save_settings(self) -> None:
        try:
            with open(SETTINGS_JSON, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log.error("Не удалось сохранить settings.json: %s", exc)

    def update_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value

    def update_gamepad_setting(self, key: str, value: Any) -> None:
        gp = self.settings.setdefault("gamepad", {})
        gp[key] = value

    def get_gamepad_cfg(self) -> Dict[str, Any]:
        cfg = self.settings.get("gamepad", {})
        out = dict(DEFAULT_SETTINGS["gamepad"])
        for k in out:
            if k in cfg:
                out[k] = cfg[k]
        return out

    # -- игры ---------------------------------------------------------------
    def load_games(self) -> None:
        self.games = []
        try:
            with open(GAMES_JSON, "r", encoding="utf-8") as f:
                raw = json.load(f)
            items = raw.get("games", []) if isinstance(raw, dict) else []
            if not isinstance(items, list):
                raise ValueError("games is not a list")
            for d in items:
                if isinstance(d, dict):
                    self.games.append(Game.from_dict(d))
        except FileNotFoundError:
            log.info("games.json отсутствует — создаю пустой.")
            self.save_games()
        except Exception as exc:
            log.warning("games.json бит (%s) — создаю дефолтный пустой.", exc)
            self.save_games()

    def save_games(self) -> None:
        try:
            payload = {"games": [g.to_dict() for g in self.games]}
            with open(GAMES_JSON, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log.error("Не удалось сохранить games.json: %s", exc)

    def add_game(self, game: Game) -> None:
        self.games.append(game)  # дописываем, не перезаписываем существующие
        self.save_games()


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    import copy as _copy
    out = _copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# ──────────────────────────────────────────────────────────────────────────────
# AssetLoader — пиксмапы, placeholder'ы, предрасчёт размытых фонов
# ──────────────────────────────────────────────────────────────────────────────
class AssetLoader:
    def __init__(self) -> None:
        self._blur_cache: "OrderedDict[str, QPixmap]" = OrderedDict()
        self._BLUR_CACHE_MAX = 12  # ~12 фонов × по одному экрану — потолок памяти

    # -- базовая загрузка ---------------------------------------------------
    def resolve(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        if p.is_absolute():
            return p
        return BASE_DIR / p

    def pixmap(self, path_str: str, size: QSize, placeholder_text: str = "") -> QPixmap:
        """Загружает изображение (center-crop под размер); при отсутствии — placeholder."""
        if path_str:
            try:
                pm = QPixmap(str(self.resolve(path_str)))
                if not pm.isNull():
                    scaled = pm.scaled(
                        size,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    x = max(0, (scaled.width() - size.width()) // 2)
                    y = max(0, (scaled.height() - size.height()) // 2)
                    return scaled.copy(x, y, size.width(), size.height())
                log.warning("Не удалось загрузить картинку: %s", path_str)
            except Exception as exc:
                log.warning("Ошибка загрузки %s: %s", path_str, exc)
        return self.placeholder(size, placeholder_text or path_str or "no image")

    def placeholder(self, size: QSize, text: str) -> QPixmap:
        pm = QPixmap(size)
        pm.fill(QColor("#1A1A1A"))
        try:
            painter = QPainter(pm)
            painter.setPen(QColor(TEXT))
            font = QFont("Segoe UI", max(9, size.width() // 16))
            painter.setFont(font)
            metrics = QFontMetrics(font)
            elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                        max(10, size.width() - 12))
            painter.drawText(QRect(QPoint(0, 0), size),
                             Qt.AlignmentFlag.AlignCenter, elided)
            painter.end()
        except Exception as exc:
            log.warning("Не удалось нарисовать placeholder: %s", exc)
        return pm

    # -- предрасчёт размытого фона (см. архитектурное решение №3) -----------
    def blurred_background(self, path_str: str, screen_size: QSize) -> QPixmap:
        """Возвращает уже размытый и растянутый под экран QPixmap (кэш по пути)."""
        cache_key = f"{path_str}|{screen_size.width()}x{screen_size.height()}"
        cached = self._blur_cache.get(cache_key)
        if cached is not None:
            self._blur_cache.move_to_end(cache_key)
        if cached is not None and not cached.isNull():
            return cached

        base: Optional[QPixmap] = None
        if path_str:
            try:
                src = QPixmap(str(self.resolve(path_str)))
                if not src.isNull():
                    base = src
            except Exception as exc:
                log.warning("Фон %s не загружается: %s", path_str, exc)
        if base is None:
            black = QPixmap(screen_size)
            black.fill(QColor("#000000"))
            self._blur_cache[cache_key] = black
            while len(self._blur_cache) > self._BLUR_CACHE_MAX:
                self._blur_cache.popitem(last=False)
            return black

        try:
            # 1. уменьшить до 25% — blur считается в разы дешевле
            small = base.scaled(
                max(1, base.width() // 4),
                max(1, base.height() // 4),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            # 2. размыть через offscreen QGraphicsScene
            scene = QGraphicsScene()
            item = scene.addPixmap(small)
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(25)
            blur.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
            item.setGraphicsEffect(blur)
            scene.setSceneRect(0, 0, small.width(), small.height())
            # ВАЖНО: в PyQt6 корректная перегрузка —
            #   render(painter: QPainter, target: QRectF, source: QRectF[, mode])
            # (QImage-перегрузки нет; раньше передавали QRect → TypeError и
            # блюр молча откатывался к резкому фону).
            result = QPixmap(small.size())
            result.fill(Qt.GlobalColor.transparent)
            painter = QPainter(result)
            scene.render(painter,
                         QRectF(0, 0, small.width(), small.height()),
                         QRectF(0, 0, small.width(), small.height()))
            painter.end()
            # 3. увеличить обратно до размера экрана
            final = result.scaled(
                screen_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        except Exception as exc:
            log.warning("Предрасчёт размытия не удался (%s) — без blur.", exc)
            final = base.scaled(
                screen_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._blur_cache[cache_key] = final
        while len(self._blur_cache) > self._BLUR_CACHE_MAX:
            self._blur_cache.popitem(last=False)
        return final


# ──────────────────────────────────────────────────────────────────────────────
# AudioEngine — музыка меню (QMediaPlayer) + SFX (QSoundEffect), мягкие фоллбэки
# ──────────────────────────────────────────────────────────────────────────────
class AudioEngine(QObject):
    def __init__(self, storage: StorageManager, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.storage = storage
        self._audio_dir = ASSETS_DIR / "audio"
        self._music_ok = MULTIMEDIA_AVAILABLE
        self._sfx: Dict[str, Any] = {}
        self._music_output: Any = None
        self.music_player: Any = None

        if not MULTIMEDIA_AVAILABLE:
            log.warning("Аудио отключено: PyQt6-Multimedia недоступен.")
            return

        # -- музыка --
        try:
            self._music_output = QAudioOutput(self)
            self.music_player = QMediaPlayer(self)
            self.music_player.setAudioOutput(self._music_output)
            try:
                self.music_player.errorOccurred.connect(self._on_music_error)
            except Exception:  # pragma: no cover
                pass
        except Exception as exc:
            self._music_ok = False
            log.warning("Не удалось создать аудио-плеер: %s — продолжаю без музыки.", exc)

        # -- SFX --
        sounds_cfg: Dict[str, str] = self.storage.settings.get("sounds", {}) or {}
        for name in ("hover", "select", "back"):
            fname = sounds_cfg.get(name, f"{name}.wav")
            path = self._audio_dir / fname
            try:
                eff = QSoundEffect(self)
                if path.exists():
                    eff.setSource(QUrl.fromLocalFile(str(path)))
                    eff.statusChanged.connect(
                        lambda st, n=name, e=eff: self._on_sfx_status(n, st, e))
                else:
                    log.warning("SFX-файл отсутствует: %s — звук '%s' не будет играть.",
                                path, name)
                self._sfx[name] = eff
            except Exception as exc:
                log.warning("Ошибка загрузки SFX '%s': %s", name, exc)

        self.apply_volumes()

    # -- callbacks ----------------------------------------------------
    def _on_music_error(self, error: Any, error_string: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            self._music_ok = False
            log.warning("QMediaPlayer ошибка (%s): %s — продолжаю без музыки.",
                        error, error_string)

    def _on_sfx_status(self, name: str, status: Any, eff: QSoundEffect) -> None:
        if status != QSoundEffect.Status.Ready:
            log.warning("SFX '%s' не загружен (status=%s) — не играю.", name, status)

    # -- API ------------------------------------------------------------
    def apply_volumes(self) -> None:
        if not MULTIMEDIA_AVAILABLE:
            return
        mv = float(self.storage.settings.get("music_volume", 70))
        sv = float(self.storage.settings.get("sfx_volume", 80))
        try:
            if self._music_output is not None:
                self._music_output.setVolume(max(0.0, min(1.0, mv / 100.0)))
        except Exception as exc:
            log.warning("Не удалось задать громкость музыки: %s", exc)
        for eff in self._sfx.values():
            try:
                eff.setVolume(max(0.0, min(1.0, sv / 100.0)))
            except Exception:
                pass

    def start_music(self) -> None:
        if not MULTIMEDIA_AVAILABLE or self.music_player is None:
            return
        if not self._music_ok:
            log.info("Музыка пропущена: ранее уже была ошибка плагина.")
            return
        fname = str(self.storage.settings.get("music_file", "menu_theme.mp3"))
        path = self._audio_dir / fname
        if not path.exists():
            log.warning("Файл музыки отсутствует: %s — работаю без неё.", path)
            return
        try:
            self.music_player.setSource(QUrl.fromLocalFile(str(path)))
            self.music_player.setLoops(QMediaPlayer.Loops.Infinite)
            self.apply_volumes()
            self.music_player.play()
            log.info("Меню-музыка: %s", path.name)
        except Exception as exc:
            self._music_ok = False
            log.warning("Не удалось запустить музыку: %s", exc)

    def reload_music(self) -> None:
        if not MULTIMEDIA_AVAILABLE or self.music_player is None:
            return
        self._music_ok = True  # пользователь мог исправить файл/громкость — даём шанс
        try:
            self.music_player.stop()
        except Exception:
            pass
        self.start_music()

    def shutdown(self) -> None:
        """Остановить проигрывание перед выходом (музыка не должна «дожидать» процесс)."""
        if not MULTIMEDIA_AVAILABLE:
            return
        try:
            if self.music_player is not None:
                self.music_player.stop()
        except Exception as exc:
            log.debug("stop music failed: %s", exc)

    def play_sfx(self, name: str) -> None:
        if not MULTIMEDIA_AVAILABLE:
            return
        eff = self._sfx.get(name)
        if eff is None:
            return
        try:
            if eff.status() == QSoundEffect.Status.Ready:
                eff.play()
        except Exception as exc:
            log.debug("SFX '%s' не сыграл: %s", name, exc)


# ──────────────────────────────────────────────────────────────────────────────
# GamepadController — pygame.joystick БЕЗ pygame.init(), hot-plug через get_count()
# ──────────────────────────────────────────────────────────────────────────────
class GamepadController(QObject):
    navigate_left = pyqtSignal()
    navigate_right = pyqtSignal()
    navigate_up = pyqtSignal()
    navigate_down = pyqtSignal()
    confirm = pyqtSignal()
    back = pyqtSignal()
    open_settings = pyqtSignal()
    open_add_game = pyqtSignal()
    emergency_exit = pyqtSignal()
    gamepad_connected = pyqtSignal(str)      # имя контроллера
    gamepad_disconnected = pyqtSignal()

    # Кнопки XInput-style
    BTN_A = 0
    BTN_B = 1
    BTN_BACK = 6
    BTN_START = 7

    DIRECTIONS = ("left", "right", "up", "down")

    def __init__(self, storage: StorageManager, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.storage = storage
        cfg = storage.get_gamepad_cfg()
        self.enabled: bool = bool(cfg["enabled"])
        self.deadzone: float = float(cfg["deadzone"])
        self.repeat_delay_ms: int = int(cfg["repeat_delay_ms"])
        self.repeat_interval_ms: int = int(cfg["repeat_interval_ms"])

        self._joy: Any = None
        self._joy_name: str = ""
        self._prev: Dict[str, bool] = {d: False for d in self.DIRECTIONS}
        self._prev_btn: Dict[int, bool] = {}
        self._press_time: Dict[str, int] = {}   # направление -> время первого нажатия
        self._last_repeat: Dict[str, int] = {}  # направление -> время последнего шага
        self._combo_start_ms: int = 0           # когда Back+Start нажаты одновременно
        self._combo_fired: bool = False

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(33)  # ~30 FPS
        self._poll_timer.timeout.connect(self._poll)

        self._hotplug_timer = QTimer(self)
        self._hotplug_timer.setInterval(2000)
        self._hotplug_timer.timeout.connect(self._hotplug_check)

        if PYGAME_AVAILABLE and self.enabled:
            try:
                pygame.joystick.init()  # ТОЛЬКО joystick-подсистема!
                log.info("pygame.joystick инициализирован (SDL2 audio не тронут).")
            except Exception as exc:
                log.warning("Не удалось инициализировать pygame.joystick: %s", exc)
                self.enabled = False
        else:
            if not PYGAME_AVAILABLE:
                log.warning("pygame недоступен — геймпад отключён, работает клавиатура.")
            self.enabled = False

        if self.enabled:
            self._hotplug_check(silent=True)
            self._poll_timer.start()
            self._hotplug_timer.start()

    # -- конфигурация из настроек ----------------------------------------
    def apply_config(self) -> None:
        cfg = self.storage.get_gamepad_cfg()
        self.deadzone = float(cfg["deadzone"])
        self.repeat_delay_ms = int(cfg["repeat_delay_ms"])
        self.repeat_interval_ms = int(cfg["repeat_interval_ms"])
        want_enabled = bool(cfg["enabled"]) and PYGAME_AVAILABLE
        if want_enabled and not self.enabled:
            self.enabled = True
            try:
                pygame.joystick.init()
            except Exception as exc:
                log.warning("pygame.joystick.init(): %s", exc)
                self.enabled = False
            if self.enabled:
                self._hotplug_check(silent=True)
                self._poll_timer.start()
                self._hotplug_timer.start()
        elif not want_enabled and self.enabled:
            self.enabled = False
            self._poll_timer.stop()
            self._hotplug_timer.stop()
            self._detach_joystick()

    @property
    def connected(self) -> bool:
        return self._joy is not None

    @property
    def joy_name(self) -> str:
        return self._joy_name

    # -- hot-plug -----------------------------------------------------------
    def _hotplug_check(self, silent: bool = False) -> None:
        if not (PYGAME_AVAILABLE and self.enabled):
            return
        try:
            count = pygame.joystick.get_count()
        except Exception as exc:
            log.warning("get_count() failed: %s", exc)
            count = 0
        if count > 0 and self._joy is None:
            self._attach_joystick()
        elif count == 0 and self._joy is not None:
            self._detach_joystick()
            if not silent:
                self.gamepad_disconnected.emit()

    def _attach_joystick(self) -> None:
        try:
            joy = pygame.joystick.Joystick(0)  # первый найденный
            joy.init()
            self._joy = joy
            self._joy_name = joy.get_name()
            log.info("Геймпад подключён: name='%s', buttons=%d, axes=%d, hats=%d",
                     self._joy_name, joy.get_numbuttons(),
                     joy.get_numaxes(), joy.get_numhats())
            self.gamepad_connected.emit(self._joy_name)
        except Exception as exc:
            log.warning("Не удалось подключить геймпад: %s", exc)
            self._joy = None
            self._joy_name = ""

    def _detach_joystick(self) -> None:
        self._joy = None
        self._joy_name = ""
        self._reset_state()

    def _reset_state(self) -> None:
        for d in self.DIRECTIONS:
            self._prev[d] = False
            self._press_time.pop(d, None)
            self._last_repeat.pop(d, None)
        self._prev_btn.clear()
        self._combo_start_ms = 0
        self._combo_fired = False

    # -- опрос ---------------------------------------------------------------
    def _poll(self) -> None:
        if self._joy is None:
            return
        now = self._ms_now()
        try:
            left = self._joy.get_axis(0) < -self.deadzone
            right = self._joy.get_axis(0) > self.deadzone
            # В pygame ось Y: -1 = вверх, +1 = вниз. D-pad hat: y=1 вверх.
            up = self._joy.get_axis(1) < -self.deadzone    # pygame: -1 = вверх
            down = self._joy.get_axis(1) > self.deadzone   # pygame: +1 = вниз
            try:
                hx, hy = self._joy.get_hat(0)
                left = left or hx == -1
                right = right or hx == 1
                up = up or hy == 1
                down = down or hy == -1
            except Exception:
                pass  # нет hat — только стики
            states = {"left": left, "right": right, "up": up, "down": down}
        except Exception as exc:
            # Текущий контроллер отключён mid-poll — переподключение
            log.warning("Чтение геймпада сорвалось (%s) — переподключение.", exc)
            was = self._joy is not None
            self._detach_joystick()
            # _hotplug_check сам эмитит disconnected, если контроллеров нет;
            # эмитим сами только если он нашёл/подключил новый.
            self._hotplug_check(silent=True)
            if was and self._joy is not None:
                pass  # переподключились к другому — connected уже эмитнут внутри
            elif was:
                self.gamepad_disconnected.emit()
            return

        self._process_directions(states, now)

        try:
            buttons = {
                self.BTN_A: self._joy.get_button(self.BTN_A) == 1,
                self.BTN_B: self._joy.get_button(self.BTN_B) == 1,
                self.BTN_BACK: self._joy.get_button(self.BTN_BACK) == 1,
                self.BTN_START: self._joy.get_button(self.BTN_START) == 1,
            }
        except Exception as exc:
            log.warning("get_button() failed (%s) — переподключение.", exc)
            was = self._joy is not None
            self._detach_joystick()
            self._hotplug_check()
            if was:
                self.gamepad_disconnected.emit()
            return

        self._process_buttons(buttons, now)

    @staticmethod
    def _ms_now() -> int:
        import time

        return int(time.monotonic() * 1000)

    def _process_directions(self, states: Dict[str, bool], now: int) -> None:
        # Самовосстановление состояния после hot-plug/ошибки чтения:
        # словарьDirections должен содержать все 4 направления.
        for d in self.DIRECTIONS:
            self._prev.setdefault(d, False)
        signals = {
            "left": self.navigate_left,
            "right": self.navigate_right,
            "up": self.navigate_up,
            "down": self.navigate_down,
        }
        for d, sig in signals.items():
            pressed = states[d]
            prev = self._prev[d]
            if pressed and not prev:
                # edge-trigger: первый шаг + старт отсчёта автоповтора
                sig.emit()
                self._press_time[d] = now
                self._last_repeat[d] = now
            elif pressed and prev:
                # удержание: автоповтор после repeat_delay, каждые repeat_interval
                t0 = self._press_time.get(d, now)
                lr = self._last_repeat.get(d, now)
                if now - t0 >= self.repeat_delay_ms and now - lr >= self.repeat_interval_ms:
                    sig.emit()
                    self._last_repeat[d] = now
            self._prev[d] = pressed

    def _process_buttons(self, buttons: Dict[int, bool], now: int) -> None:
        a = buttons[self.BTN_A]
        b = buttons[self.BTN_B]
        back = buttons[self.BTN_BACK]
        start = buttons[self.BTN_START]

        prev_a = self._prev_btn.get(self.BTN_A, False)
        prev_b = self._prev_btn.get(self.BTN_B, False)
        prev_back = self._prev_btn.get(self.BTN_BACK, False)
        prev_start = self._prev_btn.get(self.BTN_START, False)

        # Комбинация аварийного выхода: Back+Start одновременно ~1 сек
        if back and start:
            if self._combo_start_ms == 0:
                self._combo_start_ms = now
            elif not self._combo_fired and now - self._combo_start_ms >= 1000:
                self._combo_fired = True
                self.emergency_exit.emit()
        else:
            if self._combo_start_ms != 0 and self._combo_fired:
                # комбинация была активна — подавляем одиночные back/start
                pass
            self._combo_start_ms = 0
            self._combo_fired = False

        combo_active = back and start
        if a and not prev_a:
            self.confirm.emit()
        if b and not prev_b:
            self.back.emit()
        if start and not prev_start and not combo_active:
            self.open_settings.emit()
        if back and not prev_back and not combo_active:
            self.open_add_game.emit()

        self._prev_btn = dict(buttons)

    # -- shutdown -------------------------------------------------------------
    def shutdown(self) -> None:
        self._poll_timer.stop()
        self._hotplug_timer.stop()
        self._joy = None


# ──────────────────────────────────────────────────────────────────────────────
# CarouselWidget — циклическая карусель с ручным позиционированием
#   • Внешний _slot  → только QGraphicsOpacityEffect (соседи 1.0 → 0.4)
#   • Внутренний _inner → контент + QGraphicsDropShadowEffect (свечение #E60000)
#   • НИКАКИХ layout'ов для элементов: позиции через setGeometry()/move()
#   • Кнопки "⚙ Настройки" и "➕ Добавить игру" — часть карусели (циклично)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class CarouselItem:
    kind: str                    # "game" | "settings" | "add"
    title: str
    description: str = ""
    game: Optional[Game] = None


class _Slot(QWidget):
    """Внешний слот карусели: носителе QGraphicsOpacityEffect быть НЕ должно у inner."""

    def __init__(self, item: CarouselItem, assets: AssetLoader, scale: float,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.item = item
        self.assets = assets
        self.scale = scale
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(0.4)
        self.setGraphicsEffect(self.opacity_effect)

        # Внутренний контейнер — только он получает drop-shadow
        self.inner = QWidget(self)
        self.inner.setObjectName("carouselInner")
        self.inner.setStyleSheet("#carouselInner { background: transparent; }")
        self.shadow = QGraphicsDropShadowEffect(self.inner)
        self.shadow.setBlurRadius(int(round(40 * scale)))
        self.shadow.setColor(QColor(ACCENT))
        self.shadow.setOffset(0, 0)
        self.shadow.setEnabled(False)
        self.inner.setGraphicsEffect(self.shadow)

        v = QVBoxLayout(self.inner)
        m = int(round(20 * scale))
        v.setContentsMargins(m, m, m, m)
        v.setSpacing(int(round(8 * scale)))
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_label = QLabel(self.inner)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("background: transparent;")
        v.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.name_label = QLabel(item.title, self.inner)
        self.name_label.setObjectName("gameName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        v.addWidget(self.name_label)

        self.desc_label = QLabel(item.description, self.inner)
        self.desc_label.setObjectName("gameDesc")
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc_label.setWordWrap(True)
        v.addWidget(self.desc_label)

        self._icon_size = QSize(0, 0)
        self._icon_item: Optional[CarouselItem] = None

    # -- перекомпоновка под новый размер ------------------------------
    def relayout(self, slot_size: QSize, icon_size: QSize, name_h: int, desc_h: int) -> None:
        self.resize(slot_size)
        self.inner.resize(slot_size)
        # Перерисовываем иконку при смене размера ИЛИ при смене контента слота
        # (во время анимации карусели один и тот же слот переиспользуется под
        #  разные игры — без этого соседний слот показывал бы старую иконку).
        if self._icon_size != icon_size or self._icon_item is not self.item:
            self._icon_size = icon_size
            self._icon_item = self.item
            self.icon_label.setFixedSize(icon_size)
            if self.item.kind == "game" and self.item.game is not None:
                g = self.item.game
                pix = self.assets.pixmap(g.icon or g.cover, icon_size, g.title)
            else:
                pix = self.assets.pixmap("", icon_size, self.item.title)
            self.icon_label.setPixmap(pix)
        fm_name = QFontMetrics(self.name_label.font())
        elided = fm_name.elidedText(self.item.title, Qt.TextElideMode.ElideRight,
                                    max(10, slot_size.width() - int(40 * self.scale)))
        self.name_label.setText(elided)
        self.name_label.setFixedHeight(name_h)
        self.desc_label.setFixedHeight(desc_h)

    def set_active(self, active: bool) -> None:
        try:
            self.shadow.setEnabled(active)
        except Exception as exc:
            log.debug("shadow toggle failed: %s", exc)


class CarouselWidget(QWidget):
    """Циклическая карусель: активный элемент + 2 соседа. Позиции — вручную."""

    index_changed = pyqtSignal(int)          # индекс в items (для фона/топа)
    activated = pyqtSignal(int)              # нажатие A/Enter на элементе

    VISIBLE = 5   # нечётное — центральный offset 0 существует всегда, даже при 2 элементах

    def __init__(self, assets: AssetLoader, scale: float,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.assets = assets
        self.scale = scale
        self.items: List[CarouselItem] = []
        self.index: int = 0
        self._slots: List[_Slot] = []
        # Ключевое исправление: у каждого физического слота хранится ЕГО
        # визуальный offset (-1 = левый сосед, 0 = центр, +1 = правый сосед).
        # Раньше код путал индекс в списке _slots с визуальным offset — после
        # первого wrap подсветка и позиции разъезжались.
        self._slot_offset: List[int] = []
        self._pos_anims: List[Optional[QPropertyAnimation]] = []
        self._op_anims: List[Optional[QPropertyAnimation]] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    # -- размеры ---------------------------------------------------------
    def metrics(self) -> Dict[str, int]:
        w, h = self.width(), self.height()
        w = max(w, 1)
        h = max(h, 1)
        icon = int(min(300 * self.scale, w * 0.24, h * 0.5))
        icon = max(icon, int(70 * self.scale))
        slot_w = int(w * 0.42)
        slot_h = h
        name_h = int(60 * self.scale)
        desc_h = int(52 * self.scale)
        return {"icon": icon, "slot_w": slot_w, "slot_h": slot_h,
                "name_h": name_h, "desc_h": desc_h}

    # -- наполнение --------------------------------------------------------
    def set_items(self, items: List[CarouselItem], start_index: int = 0) -> None:
        for s in self._slots:
            s.deleteLater()
        self._slots.clear()
        self._slot_offset.clear()
        self._pos_anims.clear()
        self._op_anims.clear()
        self.items = items
        self.index = start_index % max(1, len(items))
        # Число слотов: не больше VISIBLE, но и не больше элементов (минимум 3 —
        # иначе при 1–2 элементах центральный offset 0 мог «уехать» из диапазона).
        n = min(self.VISIBLE, max(3, len(items)))
        if n % 2 == 0:
            n -= 1  # всегда нечётное => offset 0 существует
        half = n // 2
        offsets = list(range(-half, n - half))
        for i in range(n):
            slot = _Slot(CarouselItem("game", ""), self.assets, self.scale, self)
            self._slots.append(slot)
            self._slot_offset.append(offsets[i])
            self._pos_anims.append(None)
            self._op_anims.append(None)
        self._rebind_all()
        self.relayout_all()

    def _item_for_logical(self, logical: int) -> CarouselItem:
        return self.items[logical % len(self.items)]

    def _rebind_all(self) -> None:
        """Привязать контент каждого слота по его визуальному offset."""
        m = self.metrics()
        icon_size = QSize(m["icon"], m["icon"])
        for i, slot in enumerate(self._slots):
            off = self._slot_offset[i]
            logical = (self.index + off) % max(1, len(self.items))
            slot.item = self._item_for_logical(logical)
            slot.set_active(off == 0)
            slot.relayout(QSize(m["slot_w"], m["slot_h"]), icon_size,
                          m["name_h"], m["desc_h"])

    # -- геометрия ------------------------------------------------------------
    def _target_pos(self, offset: int) -> QPoint:
        m = self.metrics()
        step = m["slot_w"]
        cx = self.width() // 2
        cy = (self.height() - m["slot_h"]) // 2
        x = cx - m["slot_w"] // 2 + offset * step
        return QPoint(x, cy)

    def relayout_all(self) -> None:
        m = self.metrics()
        icon_size = QSize(m["icon"], m["icon"])
        for i, slot in enumerate(self._slots):
            off = self._slot_offset[i]
            slot.relayout(QSize(m["slot_w"], m["slot_h"]), icon_size,
                          m["name_h"], m["desc_h"])
            slot.move(self._target_pos(off))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self.relayout_all()

    # -- навигация ---------------------------------------------------------------
    def navigate(self, delta: int) -> bool:
        """Сдвиг карусели; возвращает True, если индекс реально изменился."""
        if len(self.items) <= 1:
            return False
        old = self.index
        self.index = (self.index + delta) % len(self.items)
        if self.index == old:
            return False
        # Эффективный визуальный шаг: при малом числе элементов (n_items < span)
        # сдвиг на весь span — no-op логически, поэтому берём остаток по модулю.
        eff = ((delta + len(self.items) // 2) % len(self.items)) - len(self.items) // 2
        if eff == 0:
            eff = delta  # например, чётное число элементов и delta=±1 -> eff=∓... не ноль
        self._animate_shift(eff if eff != 0 else delta)
        self.index_changed.emit(self.index)
        return True

    def _animate_shift(self, delta: int) -> None:
        """Сдвиг карусели. Каждый слот ЕДЕТ на visual_offset - delta; слот,
        вылетевший за край, телепортируется на противоположную сторону с новым
        контентом (до старта анимации, чтобы не был виден «прыжок»)."""
        m = self.metrics()
        icon_size = QSize(m["icon"], m["icon"])
        slot_size = QSize(m["slot_w"], m["slot_h"])
        n_slots = len(self._slots)
        n_items = max(1, len(self.items))
        duration = 250
        # Диапазон допустимых визуальных offset'ов: [-half, +half]
        half = n_slots // 2
        valid = set(range(-half, n_slots - half))
        span = 2 * half + 1  # количество визуальных позиций

        def logical_for_offset(off: int) -> int:
            return (self.index + off) % n_items

        for i, slot in enumerate(self._slots):
            old_off = self._slot_offset[i]
            final_off = old_off - delta
            if final_off not in valid:
                # Вылетел за край — телепорт ровно на один span в сторону въезда.
                wrapped_off = final_off + span * (1 if delta > 0 else -1)
                assert wrapped_off in valid, f"wrap math broken: {wrapped_off}"
                # Если элементов меньше слотов, несколько соседей показывают один
                # и тот же item — это допустимо; дубликат offset'а невозможен,
                # т.к. каждый слот сдвигается синхронно на один и тот же delta.
                self._slot_offset[i] = wrapped_off
                slot.item = self._item_for_logical(logical_for_offset(wrapped_off))
                slot.set_active(wrapped_off == 0)
                slot.relayout(slot_size, icon_size, m["name_h"], m["desc_h"])
                # Встать в стартовую точку за краем экрана, затем анимировать внутрь
                slot.move(self._target_pos(wrapped_off + delta))
                final_off = wrapped_off
            else:
                self._slot_offset[i] = final_off

            # Позиция анимируется на внешнем _slot (на нём opacity-эффект).
            self._kill_anim(i, "pos")
            anim = QPropertyAnimation(slot, b"pos", self)
            anim.setDuration(duration)
            anim.setStartValue(slot.pos())
            anim.setEndValue(self._target_pos(final_off))
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._pos_anims[i] = anim
            anim.start()

        # Прозрачность и свечение — по ЦЕЛЕВОМУ визульному offset слота,
        # а не по его индексу в списке (прежний баг: подсветка оставалась на
        # физически «центральном в списке» слоте после wrap).
        for i, slot in enumerate(self._slots):
            off = self._slot_offset[i]
            target_op = 1.0 if off == 0 else 0.4
            eff = slot.opacity_effect
            self._kill_anim(i, "op")
            a = QPropertyAnimation(eff, b"opacity", self)
            a.setDuration(duration)
            a.setStartValue(eff.opacity())
            a.setEndValue(target_op)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._op_anims[i] = a
            a.start()
            slot.set_active(off == 0)

    def _kill_anim(self, idx: int, kind: str) -> None:
        store = self._pos_anims if kind == "pos" else self._op_anims
        if idx >= len(store):
            return
        old = store[idx]
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
            store[idx] = None

    # -- активация -----------------------------------------------------------
    def current_item(self) -> Optional[CarouselItem]:
        if not self.items:
            return None
        return self.items[self.index % len(self.items)]

    def activate_current(self) -> None:
        item = self.current_item()
        if item is not None:
            self.activated.emit(self.index)


# ──────────────────────────────────────────────────────────────────────────────
# BackgroundCrossfade — две QLabel + QGraphicsOpacityEffect, предрасчитанные pixmaps
# ──────────────────────────────────────────────────────────────────────────────
class BackgroundCrossfade(QWidget):
    def __init__(self, assets: AssetLoader, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.assets = assets
        self._front_top = True
        self._anims: List[QPropertyAnimation] = []

        self.label_a = QLabel(self)
        self.label_b = QLabel(self)
        for lbl in (self.label_a, self.label_b):
            lbl.setGeometry(0, 0, 1, 1)
            lbl.setScaledContents(True)
            eff = QGraphicsOpacityEffect(lbl)
            lbl.setGraphicsEffect(eff)

        self.label_a.opacity_effect = self.label_a.graphicsEffect()
        self.label_b.opacity_effect = self.label_b.graphicsEffect()
        self.label_a.opacity_effect.setOpacity(1.0)
        self.label_b.opacity_effect.setOpacity(0.0)

        black = QPixmap(64, 64)
        black.fill(QColor("#000000"))
        self.label_a.setPixmap(black)
        self.label_b.setPixmap(black)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        for lbl in (self.label_a, self.label_b):
            lbl.setGeometry(0, 0, self.width(), self.height())

    def _visible(self) -> QLabel:
        return self.label_a if self._front_top else self.label_b

    def _hidden(self) -> QLabel:
        return self.label_b if self._front_top else self.label_a

    def set_background(self, path_str: str) -> None:
        """Кроссфейд на новый предрасчитанный размытый фон (400 мс)."""
        size = QSize(max(1, self.width()), max(1, self.height()))
        try:
            pm = self.assets.blurred_background(path_str, size)
        except Exception as exc:
            log.warning("Фон не готов: %s", exc)
            pm = QPixmap(size)
            pm.fill(QColor("#000000"))
        hidden = self._hidden()
        visible = self._visible()
        hidden.setPixmap(pm)

        for a in self._anims:
            try:
                a.stop()
            except Exception:
                pass
        self._anims.clear()

        a1 = QPropertyAnimation(hidden.opacity_effect, b"opacity", self)
        a1.setDuration(400)
        a1.setStartValue(hidden.opacity_effect.opacity())
        a1.setEndValue(1.0)
        a1.setEasingCurve(QEasingCurve.Type.OutCubic)

        a2 = QPropertyAnimation(visible.opacity_effect, b"opacity", self)
        a2.setDuration(400)
        a2.setStartValue(visible.opacity_effect.opacity())
        a2.setEndValue(0.0)
        a2.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._front_top = not self._front_top
        self._anims = [a1, a2]
        a1.start()
        a2.start()


# ──────────────────────────────────────────────────────────────────────────────
# AddGameDialog — glassmorphism-диалог добавления игры
# ──────────────────────────────────────────────────────────────────────────────
class AddGameDialog(QDialog):
    game_added = pyqtSignal(object)  # Game

    def __init__(self, scale: float, assets: AssetLoader,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.scale = scale
        self.assets = assets
        self.setObjectName("glassDialog")
        self.setWindowTitle("Добавить игру")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        screen = QApplication.primaryScreen().availableGeometry()
        w = int(screen.width() * 0.5)
        h = int(screen.height() * 0.7)
        self.resize(w, h)
        self.move((screen.width() - w) // 2, (screen.height() - h) // 2)

        root = QVBoxLayout(self)
        m = int(round(28 * scale))
        root.setContentsMargins(m, m, m, m)
        root.setSpacing(int(round(10 * scale)))

        title = QLabel("➕ Добавить игру", self)
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        hint = QLabel("Ввод текста — с клавиатуры. Навигация — геймпадом "
                      "(↑/↓ — поля, A — активация, B — отмена).", self)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        def make_field(label_text: str, placeholder: str = "") -> QLineEdit:
            lab = QLabel(label_text, self)
            lab.setObjectName("fieldLabel")
            root.addWidget(lab)
            edit = QLineEdit(self)
            edit.setPlaceholderText(placeholder)
            root.addWidget(edit)
            return edit

        self.edit_title = make_field("Название", "Cyber Drift")
        self.edit_desc = make_field("Описание", "Короткое описание игры")
        self.edit_exe = make_field("Путь к EXE", "C:/Games/Game/game.exe")

        row = QHBoxLayout()
        btn_browse = QPushButton("Обзор…", self)
        btn_browse.clicked.connect(self._browse)
        row.addStretch(1)
        row.addWidget(btn_browse)
        root.addLayout(row)
        self.btn_browse = btn_browse

        self.edit_icon = make_field("Имя иконки", "assets/icons/my_game.png")
        self.edit_cover = make_field("Имя обложки", "assets/covers/my_game.png")
        self.edit_bg = make_field("Имя фона", "assets/backgrounds/my_game.jpg")

        root.addStretch(1)

        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("Сохранить (A)", self)
        self.btn_cancel = QPushButton("Отмена (B)", self)
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

        self._fields: List[QWidget] = [
            self.edit_title, self.edit_desc, self.edit_exe,
            self.btn_browse, self.edit_icon, self.edit_cover,
            self.edit_bg, self.btn_save, self.btn_cancel,
        ]
        self._focus_i = 0
        self._set_focus(0)

    def _set_focus(self, i: int) -> None:
        self._focus_i = max(0, min(i, len(self._fields) - 1))
        try:
            self._fields[self._focus_i].setFocus(
                Qt.FocusReason.OtherFocusReason)
        except Exception as exc:
            log.debug("focus failed: %s", exc)

    # -- геймпад-навигация ------------------------------------------------
    def gp_up(self) -> None:
        self._set_focus(self._focus_i - 1)

    def gp_down(self) -> None:
        self._set_focus(self._focus_i + 1)

    def gp_confirm(self) -> None:
        w = self._fields[self._focus_i]
        if isinstance(w, QPushButton):
            w.click()
        elif isinstance(w, QLineEdit):
            w.setFocus(Qt.FocusReason.OtherFocusReason)

    def gp_back(self) -> None:
        self.reject()

    # -- действия -----------------------------------------------------------
    def _browse(self) -> None:
        try:
            fname, _ = QFileDialog.getOpenFileName(
                self, "Выберите исполняемый файл", "",
                "Программы (*.exe *.bat *.cmd);;Все файлы (*)")
            if fname:
                self.edit_exe.setText(fname.replace("\\", "/"))
        except Exception as exc:
            log.warning("QFileDialog не открылся: %s", exc)

    def _save(self) -> None:
        title = self.edit_title.text().strip()
        exe = self.edit_exe.text().strip()
        if not title or not exe:
            QMessageBox.warning(self, "Проверка",
                                "Название и путь к EXE обязательны.")
            return
        game = Game(
            id=str(uuid.uuid4()),
            title=title,
            description=self.edit_desc.text().strip(),
            exe_path=exe,
            icon=self.edit_icon.text().strip(),
            cover=self.edit_cover.text().strip(),
            background=self.edit_bg.text().strip(),
        )
        self.game_added.emit(game)
        self.accept()


# ──────────────────────────────────────────────────────────────────────────────
# SettingsDialog — Сеть / Экран / Звук / Питание
# ──────────────────────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    settings_changed = pyqtSignal()

    TABS = ("Сеть", "Экран", "Звук", "Питание")

    def __init__(self, storage: StorageManager, audio: AudioEngine,
                 scale: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.storage = storage
        self.audio = audio
        self.scale = scale
        self.setObjectName("glassDialog")
        self.setWindowTitle("Настройки")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        screen = QApplication.primaryScreen().availableGeometry()
        w = int(screen.width() * 0.7)
        h = int(screen.height() * 0.75)
        self.resize(w, h)
        self.move((screen.width() - w) // 2, (screen.height() - h) // 2)

        # debounce-таймер сохранения (п.6): single-shot 400 мс, перезапускается
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._flush_settings)

        outer = QHBoxLayout(self)
        m = int(round(24 * scale))
        outer.setContentsMargins(m, m, m, m)
        outer.setSpacing(m)

        left = QVBoxLayout()
        self.tab_labels: List[QLabel] = []
        for name in self.TABS:
            lab = QLabel(name, self)
            lab.setObjectName("tabLabel")
            left.addWidget(lab)
            self.tab_labels.append(lab)
        left.addStretch(1)
        back_hint = QLabel("B / Esc — назад на Home", self)
        back_hint.setObjectName("hint")
        left.addWidget(back_hint)
        left_w = QWidget(self)
        left_w.setLayout(left)
        left_w.setMinimumWidth(int(220 * scale))
        outer.addWidget(left_w)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._make_placeholder_tab(
            "Сеть", "Подключение к сети — заглушка.\nWi-Fi: подключено (демо)."))
        self.stack.addWidget(self._make_placeholder_tab(
            "Экран", "Разрешение и HDR — заглушка.\nЛаунчер всегда в полноэкранном режиме."))
        self.stack.addWidget(self._make_sound_tab())
        self.stack.addWidget(self._make_power_tab())
        outer.addWidget(self.stack, 1)

        self._tab_i = 2  # открываем сразу на «Звук»
        self._side_focus = True  # фокус на левом меню vs на элементах справа
        self._select_tab(self._tab_i)

    def _make_placeholder_tab(self, title: str, text: str) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        t = QLabel(title, page)
        t.setObjectName("dialogTitle")
        v.addWidget(t)
        d = QLabel(text, page)
        d.setObjectName("gameDesc")
        d.setWordWrap(True)
        v.addWidget(d)
        v.addStretch(1)
        return page

    def _make_sound_tab(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        t = QLabel("Звук", page)
        t.setObjectName("dialogTitle")
        v.addWidget(t)

        s = self.storage.settings

        v.addWidget(QLabel("Громкость музыки", page))
        self.slider_music = QSlider(Qt.Orientation.Horizontal, page)
        self.slider_music.setRange(0, 100)
        self.slider_music.setValue(int(s.get("music_volume", 70)))
        self.slider_music.valueChanged.connect(self._on_music_volume)
        v.addWidget(self.slider_music)

        v.addWidget(QLabel("Громкость эффектов (SFX)", page))
        self.slider_sfx = QSlider(Qt.Orientation.Horizontal, page)
        self.slider_sfx.setRange(0, 100)
        self.slider_sfx.setValue(int(s.get("sfx_volume", 80)))
        self.slider_sfx.valueChanged.connect(self._on_sfx_volume)
        v.addWidget(self.slider_sfx)

        sounds: Dict[str, str] = s.get("sounds", {})

        def labeled_edit(label_text: str, value: str) -> QLineEdit:
            v.addWidget(QLabel(label_text, page))
            e = QLineEdit(value, page)
            e.textChanged.connect(lambda _t: self._debounce_save())
            v.addWidget(e)
            return e

        self.edit_music_file = labeled_edit("Файл музыки", str(s.get("music_file", "")))
        self.edit_hover = labeled_edit("Файл hover", sounds.get("hover", ""))
        self.edit_select = labeled_edit("Файл select", sounds.get("select", ""))
        self.edit_back = labeled_edit("Файл back", sounds.get("back", ""))

        hint = QLabel("←/→ на геймпаде — шаг ±5 по слайдеру (с автоповтором). "
                      "Применение к плеерам — сразу; запись в файл — через debounce 400 мс.",
                      page)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)

        self._sound_widgets: List[QWidget] = [
            self.slider_music, self.slider_sfx, self.edit_music_file,
            self.edit_hover, self.edit_select, self.edit_back,
        ]
        return page

    def _make_power_tab(self) -> QWidget:
        page = QWidget(self)
        v = QVBoxLayout(page)
        t = QLabel("Питание", page)
        t.setObjectName("dialogTitle")
        v.addWidget(t)

        self.btn_min = QPushButton("Свернуть в Windows", page)
        self.btn_restart = QPushButton("Перезагрузить ПК", page)
        self.btn_shutdown = QPushButton("Выключить ПК", page)
        self.btn_min.clicked.connect(self._minimize_to_windows)
        self.btn_restart.clicked.connect(lambda: self._power("restart"))
        self.btn_shutdown.clicked.connect(lambda: self._power("shutdown"))
        for b in (self.btn_min, self.btn_restart, self.btn_shutdown):
            v.addWidget(b)

        note = QLabel("Перезагрузка/выключение отменимы командой shutdown /a "
                      "в течение 5 секунд.", page)
        note.setObjectName("hint")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)
        self._power_widgets: List[QWidget] = [self.btn_min, self.btn_restart,
                                               self.btn_shutdown]
        return page

    def _on_music_volume(self, value: int) -> None:
        self.storage.update_setting("music_volume", value)
        self.audio.apply_volumes()          # сразу к плееру
        self._debounce_save()               # в файл — с debounce

    def _on_sfx_volume(self, value: int) -> None:
        self.storage.update_setting("sfx_volume", value)
        self.audio.apply_volumes()
        self._debounce_save()

    def _debounce_save(self) -> None:
        self._save_timer.start()  # перезапуск single-shot таймера

    def _flush_settings(self) -> None:
        try:
            self.storage.update_setting("music_file", self.edit_music_file.text().strip())
            sounds = self.storage.settings.setdefault("sounds", {})
            sounds["hover"] = self.edit_hover.text().strip() or "hover.wav"
            sounds["select"] = self.edit_select.text().strip() or "select.wav"
            sounds["back"] = self.edit_back.text().strip() or "back.wav"
            self.storage.save_settings()
            self.settings_changed.emit()
        except Exception as exc:
            log.error("Flush настроек не удался: %s", exc)

    def _minimize_to_windows(self) -> None:
        top = self.window().window()
        self.accept()
        if isinstance(top, MainWindow):
            top.showMinimized()

    def _power(self, mode: str) -> None:
        label = "перезагрузить" if mode == "restart" else "выключить"
        answer = QMessageBox.question(
            self, "Подтверждение",
            f"Вы уверены, что хотите {label} компьютер?\n"
            "Действие можно отменить командой shutdown /a в течение 5 секунд.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        args = ["shutdown", "/r", "/t", "5"] if mode == "restart" \
            else ["shutdown", "/s", "/t", "5"]
        try:
            proc = subprocess.Popen(args)
        except Exception as exc:
            log.error("Не удалось запустить %s: %s", args, exc)
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось выполнить команду:\n{exc}")
            return
        check = QTimer(self)
        check.setSingleShot(True)

        def on_check() -> None:
            rc = proc.poll()
            if rc not in (0, None):
                log.error("shutdown вернул код %s (возможно, блокировка GPO).", rc)
                QMessageBox.warning(
                    self, "Ошибка",
                    f"Windows отказала в команде (код {rc}).\n"
                    "Возможно, политика группы запрещает выключение из этого аккаунта.")

        check.timeout.connect(on_check)
        check.start(700)

    def _select_tab(self, i: int) -> None:
        self._tab_i = max(0, min(i, len(self.TABS) - 1))
        self.stack.setCurrentIndex(self._tab_i)
        for k, lab in enumerate(self.tab_labels):
            lab.setObjectName("tabActive" if k == self._tab_i else "tabLabel")
            lab.style().polish(lab)
        self._side_focus = True

    def _current_right_widgets(self) -> List[QWidget]:
        idx = self.stack.currentIndex()
        if idx == 2:
            return getattr(self, "_sound_widgets", [])
        if idx == 3:
            return getattr(self, "_power_widgets", [])
        return []

    def _right_focus_index(self) -> int:
        widgets = self._current_right_widgets()
        for i, w in enumerate(widgets):
            if w.hasFocus():
                return i
        return -1

    # публичный API для Gamepad-сигналов MainWindow
    def gp_up(self) -> None:
        if self._side_focus:
            self._select_tab(self._tab_i - 1)
        else:
            i = self._right_focus_index()
            if i > 0:
                self._current_right_widgets()[i - 1].setFocus()

    def gp_down(self) -> None:
        if self._side_focus:
            self._select_tab(self._tab_i + 1)
        else:
            widgets = self._current_right_widgets()
            i = self._right_focus_index()
            if 0 <= i < len(widgets) - 1:
                widgets[i + 1].setFocus()
            elif i == -1 and widgets:
                widgets[0].setFocus()

    def gp_left(self) -> None:
        w = QApplication.focusWidget()
        if isinstance(w, QSlider):
            w.setValue(w.value() - 5)

    def gp_right(self) -> None:
        w = QApplication.focusWidget()
        if isinstance(w, QSlider):
            w.setValue(w.value() + 5)

    def gp_confirm(self) -> None:
        w = QApplication.focusWidget()
        if isinstance(w, QPushButton):
            w.click()
        elif self._side_focus:
            self._side_focus = False
            widgets = self._current_right_widgets()
            if widgets:
                widgets[0].setFocus(Qt.FocusReason.OtherFocusReason)
        elif isinstance(w, QLineEdit):
            pass  # остаёмся в поле — ввод с физической клавиатуры

    def gp_back(self) -> None:
        if not self._side_focus:
            self._side_focus = True
            self.tab_labels[self._tab_i].setFocus()
        else:
            self.reject()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # Tab-обход только внутри диалога (п.4 — на Home Tab не дублирует карусель)
        if event.key() == Qt.Key.Key_Tab:
            widgets = [] if self._side_focus else self._current_right_widgets()
            if widgets:
                i = self._right_focus_index()
                nxt = (i + 1) % len(widgets) if i >= 0 else 0
                widgets[nxt].setFocus()
                event.accept()
                return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:  # закрытие — принудительный flush (п.6)
        self._save_timer.stop()
        self._flush_settings()
        super().done(result)


# ──────────────────────────────────────────────────────────────────────────────
# MainWindow — полноэкранный лаунчер: топ-панель, фон, карусель, роутинг ввода
# ──────────────────────────────────────────────────────────────────────────────
class MainWindow(QWidget):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ardor Gaming")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)

        # --- модель / сервисы ---
        self.storage = StorageManager()
        self.assets = AssetLoader()
        self.audio = AudioEngine(self.storage, self)

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        self._base_w = max(geo.width(), 1)
        # Масштаб: базовый 1080p; при разрешении < 1280×720 — минимум 0.6
        self.scale: float = max(0.6, min(2.0, self._base_w / 1920.0))

        self.active_dialog: Optional[QDialog] = None  # AddGameDialog | SettingsDialog
        self._game_proc: Optional[subprocess.Popen] = None
        self._cursor_hidden = False

        # --- фон (за каруселью) ---
        self.background = BackgroundCrossfade(self.assets, self)
        # Фон стартует с реального размера окна: иначе первый кроссфейд
        # предрассчитает pixmap для 1x1 и фон будет растянутым/чёрным.
        geo0 = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        self.background.setGeometry(0, 0, geo0.width(), geo0.height())

        # --- центральная область ---
        central = QWidget(self)
        self.central = central
        central.setObjectName("centralArea")
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        central.setStyleSheet("#centralArea { background: transparent; }")

        self.top_bar = QFrame(central)
        self.top_bar.setObjectName("panel")
        self.top_bar.setFixedHeight(int(round(72 * self.scale)))

        top_l = QHBoxLayout(self.top_bar)
        m = int(round(20 * self.scale))
        top_l.setContentsMargins(m, 0, m, 0)
        top_l.setSpacing(m)

        logo = QLabel("ARDOR GAMING", self.top_bar)
        logo.setObjectName("logo")
        top_l.addWidget(logo)
        top_l.addStretch(1)

        self.lbl_active = QLabel("", self.top_bar)
        self.lbl_active.setObjectName("activeTitle")
        self.lbl_active.setWordWrap(False)
        self.lbl_active.setMinimumWidth(int(300 * self.scale))
        self.lbl_active.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_l.addWidget(self.lbl_active, 4)
        top_l.addStretch(1)

        # статус геймпада: PNG-иконка (без emoji) + имя контроллера
        self.gp_icon = QLabel(self.top_bar)
        self.gp_icon.setFixedSize(int(28 * self.scale), int(28 * self.scale))
        self.gp_icon.setStyleSheet("background: transparent;")
        top_l.addWidget(self.gp_icon)
        self.gp_status = QLabel("Нет геймпада", self.top_bar)
        self.gp_status.setObjectName("statusText")
        top_l.addWidget(self.gp_status)

        self.clock = QLabel("--:--", self.top_bar)
        self.clock.setObjectName("clock")
        top_l.addWidget(self.clock)

        net = QLabel("Wi-Fi", self.top_bar)
        net.setObjectName("statusText")
        top_l.addWidget(net)
        batt = QLabel("100%", self.top_bar)
        batt.setObjectName("statusText")
        top_l.addWidget(batt)

        # часы — QTimer 1 сек
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

        # --- карусель ---
        self.carousel = CarouselWidget(self.assets, self.scale, central)
        self.carousel.index_changed.connect(self._on_index_changed)
        self.carousel.activated.connect(self._on_activated)

        v = QVBoxLayout(central)
        v.setContentsMargins(int(24 * self.scale), int(24 * self.scale),
                             int(24 * self.scale), int(24 * self.scale))
        v.setSpacing(int(16 * self.scale))
        v.addWidget(self.top_bar)
        v.addWidget(self.carousel, 1)

        # --- toast-уведомления (не QMessageBox, п. «Индикация в UI») ---
        self.toast = QLabel("", self)
        self.toast.setObjectName("toast")
        self.toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toast.setWordWrap(True)
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)

        # --- скрытие курсора при бездействии мыши (3 сек) ---
        self.setMouseTracking(True)
        self._idle_cursor_timer = QTimer(self)
        self._idle_cursor_timer.setSingleShot(True)
        self._idle_cursor_timer.setInterval(3000)
        self._idle_cursor_timer.timeout.connect(self._hide_cursor)

        # --- геймпад (MainWindow не знает про pygame напрямую) ---
        self.gamepad = GamepadController(self.storage, self)
        gp = self.gamepad
        gp.navigate_left.connect(lambda: self._on_navigate(-1))
        gp.navigate_right.connect(lambda: self._on_navigate(+1))
        gp.navigate_up.connect(self._on_gp_up)
        gp.navigate_down.connect(self._on_gp_down)
        gp.confirm.connect(self._on_confirm)
        gp.back.connect(self._on_back)
        gp.open_settings.connect(self._open_settings)
        gp.open_add_game.connect(self._open_add_game)
        gp.emergency_exit.connect(self._emergency_exit)
        gp.gamepad_connected.connect(self._on_gp_connected)
        gp.gamepad_disconnected.connect(self._on_gp_disconnected)
        self._refresh_gamepad_ui()

        self._rebuild_carousel()
        self.resize(geo.size())

    # ======================================================================
    # Сборка карусели
    # ======================================================================
    def _make_items(self) -> List[CarouselItem]:
        items = [CarouselItem("game", g.title, g.description, g) for g in self.storage.games]
        items.append(CarouselItem("settings", "⚙ Настройки", "Звук, экран, питание"))
        items.append(CarouselItem("add", "➕ Добавить игру",
                                  "Новая игра в библиотеку" if items[:-2] or self.storage.games
                                  else "Добавьте первую игру"))
        return items

    def _rebuild_carousel(self, keep_index: bool = True) -> None:
        old = self.carousel.index if keep_index and self.carousel.items else 0
        items = self._make_items()
        start = min(old, len(items) - 1) if len(items) else 0
        if not self.storage.games:
            # пустая библиотека — сразу подсвечена кнопка «Добавить игру» (п.5)
            start = next((i for i, it in enumerate(items) if it.kind == "add"), 0)
        self.carousel.set_items(items, start)
        self._update_active_title()
        self._update_background()

    # ======================================================================
    # Слоты карусели
    # ======================================================================
    def _current_item(self) -> Optional[CarouselItem]:
        return self.carousel.current_item()

    def _current_game(self) -> Optional[Game]:
        it = self._current_item()
        return it.game if (it is not None and it.kind == "game") else None

    def _on_index_changed(self, _index: int) -> None:
        self.audio.play_sfx("hover")   # только edge-trigger (автоповтор — без звука)
        self._update_active_title()
        self._update_background()

    def _update_active_title(self) -> None:
        it = self._current_item()
        text = it.title if it else ""
        avail = max(120, int(self._base_w * 0.32))
        fm = QFontMetrics(self.lbl_active.font())
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, avail)
        self.lbl_active.setText(elided)
        self.lbl_active.setToolTip(text)

    def _update_background(self) -> None:
        g = self._current_game()
        path = ""
        if g is not None:
            path = g.background or g.cover or g.icon
        self.background.set_background(path)

    def _on_activated(self, index: int) -> None:
        if self.active_dialog is not None:
            return
        items = self.carousel.items
        if not items or index >= len(items):
            return
        item = items[index]
        if item.kind == "settings":
            self._open_settings()
        elif item.kind == "add":
            self._open_add_game()
        else:
            self.launch_game(item.game)

    # ======================================================================
    # Роутинг ввода: активный диалог получает всё, иначе — карусель
    # ======================================================================
    def _dialog_accepts_nav(self) -> bool:
        d = self.active_dialog
        return d is not None and isinstance(d, (AddGameDialog, SettingsDialog)) \
            and d.isVisible()

    def _on_navigate(self, delta: int) -> None:
        d = self.active_dialog
        if self._dialog_accepts_nav() and isinstance(d, SettingsDialog):
            d.gp_left() if delta < 0 else d.gp_right()
            return
        if self._dialog_accepts_nav():
            return  # ←/→ не используется в AddGameDialog
        changed = self.carousel.navigate(delta)
        if not changed:
            pass

    def _on_gp_up(self) -> None:
        d = self.active_dialog
        if self._dialog_accepts_nav():
            d.gp_up()  # type: ignore[attr-defined]
        # на Home вертикальная навигация не нужна (один ряд карусели)

    def _on_gp_down(self) -> None:
        d = self.active_dialog
        if self._dialog_accepts_nav():
            d.gp_down()  # type: ignore[attr-defined]

    def _on_confirm(self) -> None:
        d = self.active_dialog
        if self._dialog_accepts_nav():
            d.gp_confirm()  # type: ignore[attr-defined]
            return
        self.carousel.activate_current()

    def _on_back(self) -> None:
        d = self.active_dialog
        if d is not None and d.isVisible():
            self.audio.play_sfx("back")
            d.gp_back()  # type: ignore[attr-defined]
            # Диалог закрыт (visible=False), но его сигнал finished придёт только
            # в следующем витке event loop — сбрасываем состояние сразу, чтобы
            # следующее нажатие не уткнулось в «висящий» диалог.
            if self.active_dialog is d and not d.isVisible():
                self._close_dialog(d)
            return
        # B/Escape на Home → диалог «Выход / Свернуть / Отмена»
        self._home_back_dialog()

    def _quit_app(self) -> None:
        """Корректное завершение: стоп музыка + pygame quit (closeEvent не всегда
        вызывается при QApplication.quit из модального диалога)."""
        try:
            self.audio.shutdown()
        except Exception:
            pass
        try:
            self.gamepad.shutdown()
            if PYGAME_AVAILABLE:
                pygame.joystick.quit()
                pygame.quit()
        except Exception:
            pass
        QApplication.quit()

    def _home_back_dialog(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Ardor Gaming")
        box.setText("Что сделать?")
        b_exit = box.addButton("Выход из лаунчера", QMessageBox.ButtonRole.AcceptRole)
        b_min = box.addButton("Свернуть в Windows", QMessageBox.ButtonRole.ActionRole)
        b_cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_exit:
            self._quit_app()
        elif clicked is b_min:
            self.showMinimized()

    # ======================================================================
    # Диалоги
    # ======================================================================
    def _open_settings(self) -> None:
        if self.active_dialog is not None:
            return
        self.audio.play_sfx("select")
        dlg = SettingsDialog(self.storage, self.audio, self.scale, self)
        dlg.settings_changed.connect(self._on_settings_changed)
        self.active_dialog = dlg
        dlg.finished.connect(lambda _r: self._close_dialog(dlg))
        dlg.show()

    def _open_add_game(self) -> None:
        if self.active_dialog is not None:
            return
        self.audio.play_sfx("select")
        dlg = AddGameDialog(self.scale, self.assets, self)
        dlg.game_added.connect(self._on_game_added)
        self.active_dialog = dlg
        dlg.finished.connect(lambda _r: self._close_dialog(dlg))
        dlg.show()

    def _close_dialog(self, dlg: QDialog) -> None:
        if self.active_dialog is dlg:
            self.active_dialog = None
        dlg.deleteLater()
        self.activateWindow()
        self.setFocus()

    def _on_game_added(self, game: Game) -> None:
        self.storage.add_game(game)
        # стартуем на новой игре, обновляем карусель без перезапуска
        self._rebuild_carousel(keep_index=False)
        n = len(self.carousel.items)
        new_idx = next((i for i, it in enumerate(self.carousel.items)
                        if it.kind == "game" and it.game is game), n - 3 if n >= 3 else 0)
        self.carousel.index = new_idx % max(1, n)
        self.carousel._rebind_all()
        self.carousel.relayout_all()
        self._update_active_title()
        self._update_background()
        self.show_toast(f"Игра добавлена: {game.title}")

    def _on_settings_changed(self) -> None:
        self.gamepad.apply_config()
        self.audio.reload_music()
        self._refresh_gamepad_ui()

    # ======================================================================
    # Запуск игры + возврат из сворачивания
    # ======================================================================
    def launch_game(self, game: Optional[Game]) -> None:
        if game is None:
            return
        exe = Path(game.exe_path)
        try:
            exists = exe.exists()
        except Exception:
            exists = False
        if not exists:
            QMessageBox.warning(
                self, "Игра не найдена",
                f"Файл не существует:\n{game.exe_path}\n\n"
                "Проверьте путь в games.json или пересоздайте запись.")
            return
        try:
            self._game_proc = subprocess.Popen(
                [game.exe_path], cwd=os.path.dirname(game.exe_path))
            log.info("Запущена игра '%s' (pid=%s)", game.title, self._game_proc.pid)
        except Exception as exc:
            log.error("Не удалось запустить %s: %s", game.exe_path, exc)
            QMessageBox.warning(self, "Ошибка запуска", str(exc))
            self._game_proc = None
            return
        self.audio.play_sfx("select")
        self.showMinimized()          # консольный сценарий
        self._watch_proc_timer = QTimer(self)
        self._watch_proc_timer.setInterval(1000)
        self._watch_proc_timer.timeout.connect(self._check_proc)
        self._watch_proc_timer.start()

    def _check_proc(self) -> None:
        proc = self._game_proc
        if proc is None:
            self._watch_proc_timer.stop()
            return
        try:
            finished = proc.poll() is not None
        except Exception:
            finished = True
        if finished:
            self._watch_proc_timer.stop()
            self._game_proc = None
            QTimer.singleShot(500, self._restore_fullscreen)

    def _restore_fullscreen(self) -> None:
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.show_toast("Возврат в лаунчер")

    # ======================================================================
    # Аварийный выход / закрытие
    # ======================================================================
    def _emergency_exit(self) -> None:
        if self.active_dialog is not None:
            return
        answer = QMessageBox.question(
            self, "Выход",
            "Выйти из лаунчера в Windows?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._quit_app()

    # ======================================================================
    # Геймпад-индикация и toast
    # ======================================================================
    def _refresh_gamepad_ui(self) -> None:
        connected = self.gamepad.connected
        name = self.gamepad.joy_name if connected else "Нет геймпада"
        self.gp_status.setText(name)
        color = "#33CC66" if connected else TEXT2
        self.gp_status.setStyleSheet(
            f"color: {color}; font-size: {int(14 * self.scale)}px; background: transparent;")
        icon_file = "gamepad_connected.png" if connected else "gamepad_disconnected.png"
        pm = self.assets.pixmap(f"assets/icons/{icon_file}",
                               QSize(int(28 * self.scale), int(28 * self.scale)),
                               "GAMEPAD")
        self.gp_icon.setPixmap(pm)

    def _on_gp_connected(self, name: str) -> None:
        self._refresh_gamepad_ui()
        self.show_toast(f"Геймпад подключён: {name}")

    def _on_gp_disconnected(self) -> None:
        self._refresh_gamepad_ui()
        self.show_toast("Геймпад отключён")

    def show_toast(self, text: str, ms: int = 2000) -> None:
        self.toast.setText(text)
        self.toast.adjustSize()
        tw = min(self.toast.width(), int(self._base_w * 0.7))
        self.toast.setFixedWidth(tw)
        self.toast.adjustSize()
        x = (self.width() - self.toast.width()) // 2
        self.toast.move(x, int(90 * self.scale))
        self.toast.show()
        self.toast.raise_()
        self._toast_timer.start(ms)

    def _update_clock(self) -> None:
        self.clock.setText(datetime.now().strftime("%H:%M"))

    # ======================================================================
    # Раскладка (ручная для фона; центральный контейнер — на весь экран)
    # ======================================================================
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.background.setGeometry(0, 0, self.width(), self.height())
        self.central.setGeometry(0, 0, self.width(), self.height())
        self.background.lower()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.background.setGeometry(0, 0, self.width(), self.height())
        self.central.setGeometry(0, 0, self.width(), self.height())
        self.background.lower()

    # ======================================================================
    # Клавиатура (fallback)
    # ======================================================================
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        k = event.key()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.AltModifier and k == Qt.Key.Key_F4:
            self._emergency_exit()
            return
        if k == Qt.Key.Key_F1:
            self._open_settings()
            return
        if k == Qt.Key.Key_F2:
            self._open_add_game()
            return
        if self._dialog_accepts_nav():
            d = self.active_dialog
            if k in (Qt.Key.Key_Up, Qt.Key.Key_W):
                d.gp_up()  # type: ignore[attr-defined]
                return
            if k in (Qt.Key.Key_Down, Qt.Key.Key_S):
                d.gp_down()  # type: ignore[attr-defined]
                return
            if k in (Qt.Key.Key_Left, Qt.Key.Key_A) and isinstance(d, SettingsDialog):
                d.gp_left()  # type: ignore[attr-defined]
                return
            if k in (Qt.Key.Key_Right, Qt.Key.Key_D) and isinstance(d, SettingsDialog):
                d.gp_right()  # type: ignore[attr-defined]
                return
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                d.gp_confirm()  # type: ignore[attr-defined]
                return
            if k in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
                self._on_back()
                return
            super().keyPressEvent(event)
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self._on_navigate(-1)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self._on_navigate(+1)
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._on_confirm()
        elif k in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            self._on_back()
        else:
            super().keyPressEvent(event)

    # ======================================================================
    # Скрытие курсора при бездействии мыши
    # ======================================================================
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._cursor_hidden:
            QApplication.restoreOverrideCursor()
            self._cursor_hidden = False
        self._idle_cursor_timer.start()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._idle_cursor_timer.start()
        super().mousePressEvent(event)

    def _hide_cursor(self) -> None:
        if not self._cursor_hidden:
            QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
            self._cursor_hidden = True

    # ======================================================================
    # Закрытие окна — корректный teardown pygame
    # ======================================================================
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.gamepad.shutdown()
            if PYGAME_AVAILABLE:
                pygame.joystick.quit()
                pygame.quit()
        except Exception as exc:
            log.debug("pygame quit: %s", exc)
        if self._cursor_hidden:
            QApplication.restoreOverrideCursor()
            self._cursor_hidden = False
        try:
            self.audio.shutdown()
        except Exception:
            pass
        log.info("Лаунчер закрыт.")
        super().closeEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Ardor Gaming")
    mw = MainWindow()
    mw.setStyleSheet(build_qss(mw.scale))
    mw.showFullScreen()
    mw.audio.start_music()
    sys.exit(app.exec())
