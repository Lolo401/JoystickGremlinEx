# -*- coding: utf-8; -*-

# Based in part on original Joystick Gremlin work by Lionel Ott and other contributors - Gremlin Ex is (C) EMCS 2026
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""OBS chromakey overlay designer and capture window."""

from __future__ import annotations

import logging

from PySide6 import QtCore
from shiboken6 import Shiboken

import gremlin.event_handler
import gremlin.shared_state
import gremlin.util
from gremlin.singleton_decorator import SingletonDecorator

from .bindings import read_toggle_active
from .designer import OverlayDesignerWidget
from .model import OverlayScene, is_onscreen_mode, normalize_background_mode
from .overlay_window import OverlayWindow, apply_onscreen_geometry

syslog = logging.getLogger("system")


@SingletonDecorator
class OverlayManager:
    """Owns the shared scene, designer, and overlay window."""

    def __init__(self):
        self.scene = OverlayScene()
        self._overlay = None
        self._hooks = False
        self._auto_shown = False
        self._last_mode = None
        self._toggle_timer = None
        self._toggle_active = False
        self._bind_profile_hooks()
        self.scene.load_for_profile()
        apply_onscreen_geometry(self.scene)
        self._last_mode = normalize_background_mode(self.scene.canvas.get("background_mode"))
        self.scene.changed.connect(self._on_scene_changed)

    def _bind_profile_hooks(self):
        if self._hooks:
            return
        el = gremlin.event_handler.EventListener()
        el.profile_loaded.connect(self._on_profile_loaded)
        el.profile_unloaded.connect(self._on_profile_unloaded)
        el.profile_started.connect(self._on_profile_started)
        el.profile_stop.connect(self._on_profile_stop)
        el.tabs_loaded.connect(self._on_tabs_loaded)
        self._hooks = True

    def _load_current_profile_scene(self):
        self.scene.load_for_profile()
        apply_onscreen_geometry(self.scene)
        self._last_mode = normalize_background_mode(self.scene.canvas.get("background_mode"))

    def _on_profile_loaded(self):
        if self.scene.dirty:
            self.scene.save_owned()
        self._load_current_profile_scene()

    def _on_profile_unloaded(self):
        if self.scene.dirty:
            self.scene.save_owned()
        gremlin.util.InvokeUiMethod(self._stop_runtime_toggle)
        self.hide_overlay()
        # New Profile never emits profile_loaded; drop the previous layout now
        # so the designer does not keep showing it on the empty profile.
        self._load_current_profile_scene()

    def _on_tabs_loaded(self):
        self._ensure_current_profile_scene()

    def _on_profile_started(self):
        gremlin.util.InvokeUiMethod(self._start_runtime_toggle)
        if self.scene.canvas.get("show_on_profile_start"):
            self._auto_shown = True
            QtCore.QTimer.singleShot(0, lambda: self.show_overlay(auto=True))

    def _on_profile_stop(self):
        gremlin.util.InvokeUiMethod(self._stop_runtime_toggle)
        if self._auto_shown or self.scene.canvas.get("show_on_profile_start"):
            self._auto_shown = False
            self.hide_overlay()

    def _start_runtime_toggle(self):
        binding = self.scene.canvas.get("toggle_binding")
        self._toggle_active = read_toggle_active(binding)
        if self._toggle_timer is None:
            timer = QtCore.QTimer()
            timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
            timer.setInterval(16)
            timer.timeout.connect(self._poll_toggle)
            self._toggle_timer = timer
        if not self._toggle_timer.isActive():
            self._toggle_timer.start()

    def _stop_runtime_toggle(self):
        if self._toggle_timer is not None:
            self._toggle_timer.stop()
        self._toggle_active = False

    def _poll_toggle(self):
        binding = self.scene.canvas.get("toggle_binding")
        active = read_toggle_active(binding)
        rising = active and not self._toggle_active
        self._toggle_active = active
        if not rising:
            return
        if self.overlay_is_visible():
            self._auto_shown = False
            self.hide_overlay()
        else:
            self._auto_shown = True
            self.show_overlay(auto=True)

    def _ensure_current_profile_scene(self):
        if self.scene.belongs_to_profile():
            return
        if self.scene.dirty:
            self.scene.save_owned()
        self._load_current_profile_scene()

    def _on_scene_changed(self):
        mode = normalize_background_mode(self.scene.canvas.get("background_mode"))
        if mode == self._last_mode or not self.overlay_is_visible():
            self._last_mode = mode
            return
        self._last_mode = mode
        gremlin.util.InvokeUiMethod(self._recreate_overlay_ui)

    def _recreate_overlay_ui(self):
        self._hide_overlay_ui()
        self._show_overlay_ui()

    def launch_designer(self, parent=None):
        gremlin.util.InvokeUiMethod(self._launch_designer_ui, parent)

    def _launch_designer_ui(self, parent=None):
        self._ensure_current_profile_scene()
        ui = gremlin.shared_state.ui
        guid = gremlin.shared_state.overlay_tab_guid
        if ui is not None:
            ui.selectTabWidget(guid)
            return
        syslog.warning("OBS OVERLAY: main window is not ready; Overlay tab cannot be selected")

    def overlay_is_visible(self) -> bool:
        return self._overlay is not None and Shiboken.isValid(self._overlay) and self._overlay.isVisible()

    def show_overlay(self, auto: bool = False):
        gremlin.util.InvokeUiMethod(self._show_overlay_ui, auto)

    def _show_overlay_ui(self, auto: bool = False):
        try:
            self._ensure_current_profile_scene()
            apply_onscreen_geometry(self.scene)
            if self._overlay is not None and Shiboken.isValid(self._overlay):
                self._overlay._apply_window_flags()
                self._overlay.show()
                if not is_onscreen_mode(self.scene.canvas):
                    self._overlay.raise_()
                return
            window = OverlayWindow(self.scene)
            window.destroyed.connect(self._overlay_destroyed)
            self._overlay = window
            window.show()
            if auto:
                syslog.info("OBS OVERLAY: window opened for profile start")
        except Exception as err:
            syslog.error(f"OBS OVERLAY: failed to open overlay window: {err}")

    def _overlay_destroyed(self, *args):
        self._overlay = None

    def hide_overlay(self):
        gremlin.util.InvokeUiMethod(self._hide_overlay_ui)

    def _hide_overlay_ui(self):
        if self._overlay is not None and Shiboken.isValid(self._overlay):
            self._overlay.hide()
            self._overlay.close()
        self._overlay = None


def launch_designer(parent=None):
    OverlayManager().launch_designer(parent)


def show_overlay(auto: bool = False):
    OverlayManager().show_overlay(auto=auto)


def hide_overlay():
    OverlayManager().hide_overlay()


def persist_for_profile(profile) -> bool:
    """Write the in-memory overlay into the given profile if it owns the scene."""
    try:
        if OverlayManager.instance is None:
            return False
        scene = OverlayManager().scene
        current = gremlin.shared_state.current_profile
        if current is not profile:
            return False
        if scene._profile_key and not scene.belongs_to_profile(profile):
            return False
        return scene.save_to_profile(profile)
    except Exception as err:
        syslog.warning(f"OBS OVERLAY: persist on profile save failed: {err}")
        return False


def current_scene() -> OverlayScene:
    return OverlayManager().scene
