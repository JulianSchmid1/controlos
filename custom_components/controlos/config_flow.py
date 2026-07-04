"""ControlOS - Config-Flow: Bereich per Name anlegen."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries

from .const import DOMAIN


class ControlosConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Legt pro Bereich einen Config-Entry an (Name-Eingabe)."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            name = (user_input.get("name") or "").strip()
            if not name:
                errors["name"] = "name_required"
            else:
                await self.async_set_unique_id(name.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data={"name": name})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("name", default=""): str}),
            errors=errors,
        )

    async def async_step_import(self, import_data):
        """Bereich per Service anlegen - oder den Phasen-Standard-Hub."""
        if import_data.get("hub"):
            await self.async_set_unique_id("controlos_hub")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Phasen-Standard", data={"hub": True})
        name = (import_data.get("name") or "").strip()
        if not name:
            return self.async_abort(reason="name_required")
        await self.async_set_unique_id(name.lower())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=name, data={"name": name})
