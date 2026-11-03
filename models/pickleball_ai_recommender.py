import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PickleballAiRecommender(models.AbstractModel):
    """Layers a best-effort live Alobo availability check onto the weekly
    session suggestion when alobo_connector is installed."""
    _inherit = 'pickleball.ai.recommender'

    def _check_live_court_availability(self, court, day):
        # Scraper flakiness must never block the suggestion — log and move on.
        if not court or not court.alobo_branch_id:
            return
        slots = self.env['pickleball.court']._get_booking_schedule(court, day)
        if slots is None:
            _logger.warning(
                "AI weekly suggestion: live schedule check failed for %s, "
                "proceeding with historical suggestion anyway", court.name)
