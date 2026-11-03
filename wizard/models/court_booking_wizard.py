import logging

from odoo import fields, models, Command, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PickleballCourtSchedule(models.TransientModel):
    _name = 'pickleball.court.schedule'
    _description = 'Court Booking Schedule Lookup'

    court_id = fields.Many2one(
        comodel_name='pickleball.court',
        string='Court',
        required=True,
        domain=[('alobo_branch_id', '!=', False)],
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.today,
    )
    state = fields.Selection(
        selection=[('search', 'Search'), ('done', 'Done')],
        default='search',
        required=True,
    )
    slot_ids = fields.One2many(
        comodel_name='pickleball.court.schedule.slot',
        inverse_name='schedule_id',
        string='Booking Slots',
        readonly=True,
    )
    total_slots = fields.Integer(string='Total Slots', default=0, readonly=True)
    available_slots = fields.Integer(string='Available', default=0, readonly=True)

    def action_search(self) -> dict:
        self.ensure_one()
        slots = self.env['pickleball.court']._get_booking_schedule(self.court_id, self.date)
        if slots is None:
            raise UserError(_(
                "Lookup failed. Check server logs, or verify Playwright is installed:\n"
                "  pip install playwright\n  playwright install chromium"
            ))

        slot_commands = [Command.clear()]
        for slot in slots:
            slot_commands.append(Command.create(slot))

        available = sum(1 for s in slots if s.get('status') == 'available')
        self.write({
            'slot_ids': slot_commands,
            'state': 'done',
            'total_slots': len(slots),
            'available_slots': available,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pickleball.court.schedule',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_new_search(self) -> dict:
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pickleball.court.schedule',
            'view_mode': 'form',
            'target': 'new',
        }


class PickleballCourtScheduleSlot(models.TransientModel):
    _name = 'pickleball.court.schedule.slot'
    _description = 'Court Booking Slot'
    _order = 'time_start asc, yard_name asc'

    schedule_id = fields.Many2one(
        comodel_name='pickleball.court.schedule',
        string='Schedule',
        required=True,
        ondelete='cascade',
        index=True,
    )
    yard_name = fields.Char(string='Court', readonly=True)
    time_start = fields.Char(string='From', readonly=True)
    time_end = fields.Char(string='To', readonly=True)
    status = fields.Selection(
        selection=[('available', 'Available'), ('booked', 'Booked')],
        string='Status',
        readonly=True,
    )
    price = fields.Float(string='Price (VND)', readonly=True, digits=(15, 0))
