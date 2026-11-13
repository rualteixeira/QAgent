"""Argumentos das ferramentas do executor LLM. As descrições vão para o LLM: têm de ser genéricas (nenhuma app
concreta) — verificado por tests/test_prompts_app_agnostic.py."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RefArgs(BaseModel):
    ref: str = Field(description="Element ref from the latest screen description, e.g. 'e7'")


class TypeArgs(RefArgs):
    text: str = Field(description="Text to type; use {{testData.<key>}} placeholders for test data")
    submit: bool = Field(False, description="Press Enter after typing")


class SwipeArgs(BaseModel):
    direction: Literal["up", "down", "left", "right"] = Field(
        description="Finger direction: 'left' shows the next page of a horizontal pager; 'up' moves content up")
    ref: str | None = Field(None, description="Optional element to swipe within (e.g. a horizontal pager)")


class ScrollArgs(BaseModel):
    direction: Literal["up", "down"] = Field(description="'down' reveals content further down")
    ref: str | None = Field(None, description="Optional scrollable container ref")


class ScrollToArgs(BaseModel):
    text: str = Field(description="Visible text or accessibility description to scroll to (substring)")
    direction: Literal["up", "down"] = "down"


class KeyArgs(BaseModel):
    key: Literal["back", "home", "enter", "delete", "tab", "search", "escape", "space", "hide_keyboard"]


class ListAppsArgs(BaseModel):
    filter: str | None = Field(None, description="Optional case-insensitive substring of the package name")


class OpenAppArgs(BaseModel):
    package: str = Field(description="Package name from list_apps")
    restart: bool = Field(False, description="Close the app first and start it fresh (keeps its data)")


class PointArgs(BaseModel):
    x: int = Field(ge=0, description="Horizontal position in pixels of the latest screenshot (look_at_screen)")
    y: int = Field(ge=0, description="Vertical position in pixels of the latest screenshot (look_at_screen)")


class DragArgs(BaseModel):
    from_ref: str | None = Field(None, description="Element to drag (ref from the latest screen description)")
    from_x: int | None = Field(None, ge=0, description="Start position (latest screenshot pixels) when not listed")
    from_y: int | None = Field(None, ge=0, description="Start position (latest screenshot pixels) when not listed")
    to_ref: str | None = Field(None, description="Element to drag onto (ref)")
    to_x: int | None = Field(None, ge=0, description="End position (latest screenshot pixels)")
    to_y: int | None = Field(None, ge=0, description="End position (latest screenshot pixels)")
    hold: bool = Field(True, description="true: press and hold first, then move (move or reorder items); "
                                         "false: move directly (sliders, drawing)")


class CloseAppsArgs(BaseModel):
    packages: list[str] | None = Field(
        None, description="Packages to close (from list_apps). Omit to close every app used in this test")


class WaitArgs(BaseModel):
    seconds: float = Field(ge=0.5, le=60)


class WaitTextArgs(BaseModel):
    text: str = Field(description="Text (case-insensitive substring) to wait for, in text or description")
    timeout_sec: float = Field(10, ge=1, le=120)
    gone: bool = Field(False, description="Wait until the text DISAPPEARS instead")


class ScreenArgs(BaseModel):
    filter: str | None = Field(None, description="Optional case-insensitive substring to filter elements")


class HumanArgs(BaseModel):
    instruction: str = Field(description="What the tester must do on the device (short, imperative), "
                                         "in the language of the step")


class Assertion(BaseModel):
    kind: Literal["visible", "absent", "text_equals", "text_contains", "count"] = Field(
        description="visible: element (ref) or text is on screen; absent: text is NOT on screen; "
                    "text_equals/text_contains: text of element ref; count: number of elements like ref (same id)")
    ref: str | None = Field(None, description="Element ref from the latest screen description")
    text: str | None = Field(None, description="Expected text (text_equals/text_contains), or the text for "
                                               "visible/absent when there is no ref")
    op: Literal["eq", "ge"] = Field("eq", description="count: eq = exactly, ge = at least")
    count: int | None = Field(None, ge=0, description="count: expected number")


class FinishArgs(BaseModel):
    status: Literal["passed", "failed"]
    reason: str = Field(description="Short justification with the observed evidence")
    assertion: Assertion | None = Field(
        None, description="[THEN] steps: REQUIRED when passed — the machine-checkable check that proves the "
                          "expected result (it is re-verified on a fresh screen and becomes an assert in the "
                          "generated test). Also when failed: the check of what was EXPECTED (re-verified as not met).")
    how: Literal["performed", "done_by_tester", "already_done_by_step", "already_true_before_test"] = Field(
        "performed", description="[WHEN] steps: performed = you did the action in this step; "
        "done_by_tester = the human tester did it in this step after request_human; "
        "already_done_by_step = an EARLIER step of this test did exactly this (set already_done_by_step); "
        "already_true_before_test = the result already existed before this test started (you did nothing)")
    already_done_by_step: int | None = Field(
        None, description="With how=already_done_by_step: number of that earlier step")


ALL_SCHEMAS = (RefArgs, TypeArgs, SwipeArgs, ScrollArgs, ScrollToArgs, KeyArgs, ListAppsArgs, OpenAppArgs, PointArgs, DragArgs, CloseAppsArgs, WaitArgs,
               WaitTextArgs, ScreenArgs, HumanArgs, Assertion, FinishArgs)
