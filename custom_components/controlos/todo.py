"""ControlOS - Grow-Notizen & Erinnerungen je Bereich (Todo-Liste).

Persistiert im zentralen ControlOS-Store (.storage/controlos.data),
bedienbar ueber die native HA-Todo-Karte im Grow-Kalender.
"""
from __future__ import annotations

import uuid
from datetime import date

from homeassistant.components.todo import (TodoItem, TodoItemStatus,
                                           TodoListEntity,
                                           TodoListEntityFeature)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity_base import area_slug, device_info_for


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    async_add_entities([ControlosTodo(entry)])


def _to_item(d: dict) -> TodoItem:
    due = None
    if d.get("due"):
        try:
            due = date.fromisoformat(d["due"])
        except ValueError:
            due = None
    return TodoItem(
        summary=d.get("summary", ""),
        uid=d.get("uid"),
        status=(TodoItemStatus.COMPLETED if d.get("status") == "completed"
                else TodoItemStatus.NEEDS_ACTION),
        due=due,
        description=d.get("description"))


def _to_dict(item: TodoItem) -> dict:
    return {
        "uid": item.uid or uuid.uuid4().hex,
        "summary": item.summary or "",
        "status": ("completed" if item.status == TodoItemStatus.COMPLETED
                   else "needs_action"),
        "due": item.due.isoformat() if item.due else None,
        "description": item.description,
    }


class ControlosTodo(TodoListEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:notebook-edit"
    _attr_name = "Grow-Notizen"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

    def __init__(self, entry: ConfigEntry):
        self._entry = entry
        self._attr_unique_id = "%s_notizen" % entry.entry_id
        self.entity_id = "todo.controlos_%s_notizen" % area_slug(entry.title)

    @property
    def device_info(self):
        return device_info_for(self._entry)

    def _store(self):
        return self.hass.data.get(DOMAIN, {}).get("store")

    def _items(self) -> list[dict]:
        store = self._store()
        return store.todos(self._entry.entry_id) if store else []

    def _save(self, items: list[dict]) -> None:
        store = self._store()
        if store:
            store.set_todos(self._entry.entry_id, items)
        self.async_write_ha_state()

    @property
    def todo_items(self) -> list[TodoItem] | None:
        return [_to_item(d) for d in self._items()]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        items = self._items()
        items.append(_to_dict(item))
        self._save(items)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        items = self._items()
        for i, d in enumerate(items):
            if d.get("uid") == item.uid:
                items[i] = _to_dict(item)
                break
        self._save(items)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        items = [d for d in self._items() if d.get("uid") not in uids]
        self._save(items)
