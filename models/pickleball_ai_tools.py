from datetime import datetime

from odoo import fields, models

from .pickleball_ai_commands import _SCRAPER_TOOL_TIMEOUT

_COURT_TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "search_available_courts",
            "description": "Live-search the Alobo booking platform for pickleball courts with "
                            "open slots in a province/ward and time window. Can take ~30-90s.",
            "parameters": {
                "type": "object",
                "properties": {
                    "province_name": {"type": "string", "description": "e.g. 'Hà Nội'"},
                    "ward_name": {"type": "string"},
                    "date_start": {"type": "string", "description": "ISO datetime"},
                    "date_end": {"type": "string", "description": "ISO datetime"},
                },
                "required": ["province_name", "date_start", "date_end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_court_schedule",
            "description": "Get a specific court's booking schedule for one date "
                            "(which slots are already booked).",
            "parameters": {
                "type": "object",
                "properties": {
                    "court_name": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["court_name", "date"],
            },
        },
    },
]


class PickleballAiToolsAlobo(models.AbstractModel):
    """Live Alobo court tools layered onto the AI tool registry when the
    alobo_connector module is installed."""
    _inherit = 'pickleball.ai.tools'

    def _tool_specs(self) -> list:
        return super()._tool_specs() + _COURT_TOOL_SPECS

    def _tool_search_available_courts(self, conversation=None, province_name=None,
                                      ward_name=None, date_start=None, date_end=None):
        province = self.env['res.country.state'].search([
            ('country_id.code', '=', 'VN'), ('name', 'ilike', province_name),
        ], limit=1)
        if not province:
            return {"error": f"No Vietnamese province/city matching '{province_name}'"}
        ward_code = None
        if ward_name:
            ward = self.env['res.country.ward'].search([
                ('state_id', '=', province.id), ('name', 'ilike', ward_name),
            ], limit=1)
            ward_code = ward.code if ward else None

        try:
            dt_start = datetime.fromisoformat(date_start)
            dt_end = datetime.fromisoformat(date_end)
        except (ValueError, TypeError):
            return {"error": "date_start/date_end must be ISO datetime strings"}

        branches = self.env['alobo.client'].search_available_branches(
            province_code=province.external_code, date_start=dt_start, date_end=dt_end,
            ward_code=ward_code, timeout=_SCRAPER_TOOL_TIMEOUT,
        )
        if branches is None:
            return {"error": "Court search failed (scraper error or timeout). Try again later."}
        return {
            "venues": [
                {
                    "name": b.get("name"), "address": b.get("address"),
                    "available_courts": [y.get("name") for y in b.get("availableYards", [])],
                }
                for b in branches if b.get("availableYards")
            ]
        }

    def _tool_get_court_schedule(self, conversation=None, court_name=None, date=None):
        court = self.env['pickleball.court'].search([
            ('name', 'ilike', court_name), ('alobo_branch_id', '!=', False),
        ], limit=1)
        if not court:
            return {"error": f"No synced court matching '{court_name}'"}
        try:
            day = fields.Date.from_string(date)
        except (ValueError, TypeError):
            return {"error": "date must be YYYY-MM-DD"}

        slots = self.env['pickleball.court']._get_booking_schedule(court, day, timeout=_SCRAPER_TOOL_TIMEOUT)
        if slots is None:
            return {"error": "Schedule lookup failed (scraper error or timeout). Try again later."}
        return {"court": court.name, "date": date, "booked_slots": slots}
